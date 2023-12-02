import socket
import threading
import time
import selectors
import random

from LDProtocol import LDProtocol
from CyclicRedundancyCheck import CRC
import prijmatel


class Packet:
    def __init__(self, flags, number, message, protocol):
        self.flags = flags
        self.number = number  # poradie % LDProtocol.WINDOW_SIZE
        self.checksum = CRC(message)
        self.message = message

        self.protocol = protocol

        self.ack = False

        self.timer = threading.Timer(self.protocol.rtt, self.reschedule)

    def reschedule(self):
        """
        Ak nie je packet pripraveny na opa prida datagram ku packetom na znovu odoslanie
        :return:
        """
        if self not in self.protocol.to_resend:
            self.timer = threading.Timer(self.protocol.rtt, self.reschedule)

            with self.protocol.resend_lock:
                self.protocol.to_resend.append(self)

    def stop_timer(self):
        """
        Zastavi casovac
        :return:
        """
        self.timer.cancel()

    def out(self):
        """
        vytvori spravu na odoslanie
        zapne casovac hned pred vratenim spravy
        :return: 
        """
        _out = (bytes([self.flags, self.number])
                + int.to_bytes(self.checksum, length=2, byteorder="big")
                + self.message)
        self.timer.start()
        return _out


class Sender:
    def __init__(self, host=None, port=None, message=None, file_name=None,
                 sock=None, protocol=LDProtocol(5)):
        self.message = self.construct_message(file_name, message)
        self.last_sent_index = 0
        self.next_seq = 0

        self.is_file = False if file_name is None else True

        # pri inicializacii mame packet oznacujuci zaciatok spravy na 0. byte
        self.datagrams = []

        if sock is None:
            self.comm_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        else:
            self.comm_socket = sock

        self.comm_socket.connect((host, port))

        self.selector = selectors.DefaultSelector()
        self.selector.register(self.comm_socket, selectors.EVENT_WRITE | selectors.EVENT_READ)

        self.protocol = protocol

        self.alive_thread = threading.Thread(target=self.keep_alive, daemon=True)

    @staticmethod
    def construct_message(filename, message):
        if filename is None:
            return message.encode("utf-8")
        return filename.encode("utf-8") + bytes([0]) + message.encode()

    def get_number_packet(self, number):
        i = 0
        while number != self.datagrams[i].number:
            if i >= LDProtocol.WINDOW_SIZE:
                raise LookupError("hladany packet sa nenasiel")
            i += 1
        return i

    def init_comm(self):
        start_time = time.monotonic()
        flags = LDProtocol.START

        if self.is_file:
            flags |= LDProtocol.FILE
        while True:
            try:
                self.comm_socket.send(bytes([flags, 0, 0, 0]))

                # selector ak nedostaneme odpoved do 5s
                events = self.selector.select(5)
                message = bytes([0, 0, 0, 0])  # default odpoved
                for key, mask in events:
                    if mask & selectors.EVENT_READ:
                        message, source = self.comm_socket.recvfrom(509)
            except socket.error as e:
                print(e)
                print("ukoncime pokus o spojenie...")
                return
            if (message[0] & (LDProtocol.START | LDProtocol.ACK)) == (LDProtocol.START | LDProtocol.ACK):
                return self.send()
            elif (message[0] & (LDProtocol.START | LDProtocol.NACK)) == (LDProtocol.START | LDProtocol.NACK):
                print("server neprijal nase spojenie")
                return
            else:
                time.sleep(true_interval(5, start_time))

    def end_comm(self):
        print("Ukoncenie spravy, posleme FIN")
        self.comm_socket.send(bytes([LDProtocol.FIN, 0, 0, 0]))

    def send(self):
        self.comm_socket.setblocking(False)
        packet_size = 504  # todo packet size

        # todo casovac pouziva RTT, asi ziskany z Keep Alive
        #  rtt viem zistit aj z ack/nack

        # opakujeme kym mame nieco poslat
        while self.datagrams or self.last_sent_index < len(self.message):
            if not any(self.protocol.is_alive):
                # ak sme na posledne 3 Keep Alive nedostali odpoved
                # ukoncime spojenie

                print("stratili sme spojenie...")
                break

            events = self.selector.select()
            for key, mask in events:
                if mask & selectors.EVENT_READ:
                    # precitame 1 packet
                    self.read(key)

                if mask & selectors.EVENT_WRITE:
                    # odosleme max 1 packet
                    self.write(key, packet_size)

            if len(self.datagrams) == 0 and self.protocol.prepare_swap:
                # sme pripraveny na swap
                self.comm_socket.send(bytes([LDProtocol.SWAP | LDProtocol.ACK, 0, 0, 0]))
                self.swap()

            if len(self.datagrams) == 0 and self.last_sent_index >= len(self.message):
                # ak sme odoslali celu spravu a uz nic neocakava znovu odoslabie
                return self.end_comm()

    def read(self, key):
        conn = key.fileobj

        # dostaneme naspat hlavicku s nulovym checksum
        message = conn.recv(4)

        if ((message[0] & (LDProtocol.KEEP_ALIVE | LDProtocol.ACK))
                == (LDProtocol.KEEP_ALIVE | LDProtocol.ACK)):
            # ak sme dostali ack na Keep Alive zapamatame si odpoved
            with self.protocol.alive_lock:
                self.protocol.is_alive[-1] = True

        elif ((message[0] & (LDProtocol.SWAP | LDProtocol.ACK))
              == (LDProtocol.SWAP | LDProtocol.ACK)):
            # todo nie je toto full pepe?
            # ak sme dostali odpoved na swap, swapneme
            self.swap()

        elif message[0] & LDProtocol.SWAP:
            # ak sme dostali poziadavku na swap, zacneme sa pripravovat sa na swap
            self.protocol.prepare_swap = True

        elif message[0] & LDProtocol.ACK:
            # kladna odpoved na prijaty packet

            # zistime na ktory packet z okna sme prijali odpoved
            k = self.get_number_packet(message[1])
            packet = self.datagrams[k]
            packet.ack = True

            packet.stop_timer()

            # spocitame pocet packetov za sebou s ACK od prveho
            j = 0
            while j < len(self.datagrams) and self.datagrams[j].ack:
                j += 1

            # nasledne tieto packety odstranime z okna
            for k in range(j):
                self.datagrams.pop(0)

        elif message[0] & LDProtocol.NACK:
            # zaporna odpoved na packet

            # zistime na ktory packet z okna sme prijali odpoved
            k = self.get_number_packet(message[1])
            packet = self.datagrams[k]

            packet.stop_timer()
            packet.reschedule()

    def write(self, key, packet_size):
        conn = key.fileobj
        if packet_size == -1:
            # SWAP posielame ak je poziadavka na packet o velkosti -1
            print("SWAP request sent")
            conn.send(bytes([LDProtocol.SWAP, 0, 0, 0]))
            self.protocol.prepare_swap = True
            return

        elif len(self.protocol.to_resend) != 0:
            # pokusime sa opatovne poslat stary packet

            print("resend")
            with self.protocol.resend_lock:
                packet = self.protocol.to_resend.pop(0)
                # ak packet je dalsi packet na resent, a tento nie je v datagramoch skusime znovu
                while self.protocol.to_resend and packet not in self.datagrams:
                    packet = self.protocol.to_resend.pop(0)

            # ak je tento packet v datagramoch posleme ho
            if packet in self.datagrams:
                conn.send(packet.out())
                return
            # inak sa pokusime poslat novy packet

        if (not self.protocol.prepare_swap
                and len(self.datagrams) < LDProtocol.WINDOW_SIZE and self.last_sent_index < len(self.message)):
            # alebo poslem novy
            flags = 0
            # print("write", [i.ack for i in self.datagrams])

            start = self.last_sent_index
            end = start + packet_size
            self.last_sent_index = end

            if start == 0 and self.is_file == 1:
                flags |= LDProtocol.FILE

            # out of range slicing is handled gracefully
            message = self.message[start:end]

            # do datagramov pridame packet, ostane tam kym nedostaneme ack
            self.datagrams.append(Packet(flags, self.next_seq, message, self.protocol))

            conn.send(self.datagrams[-1].out())

            self.next_seq = (self.next_seq + 1) % LDProtocol.BUFFER_SIZE

    def swap(self):
        self.protocol.prepare_swap = False
        self.protocol.confirmed_swap = False
        # precital poznamku u odosielatela
        # pozastavime alive_thread
        # zapneme vlastneho prijimatela
        # po ukonceni prijimatela znovu zapneme alive_thread
        self.protocol.keep_alive_flag.clear()
        # todo prepneme sa na prijimatela
        novy = prijmatel.Reciever(sock=self.comm_socket.dup())
        novy.recieve()
        self.protocol.keep_alive_flag.set()

    def keep_alive(self):
        """
        Posle packet s Keep Alive znackou, potom caka 5 sekund a kym sa znovu nenastavi vlajka na posielanie.

        Pomocou zvyšku po delení času intervalom zaisťujeme odoslanie v priemere každých interval sekúnd.
        :return:
        """
        interval = 5
        start_time = time.monotonic()
        while any(self.protocol.is_alive):
            self.comm_socket.send(bytes([4, 0, 0, 0]))

            with self.protocol.alive_lock:
                self.protocol.is_alive.pop(0)
                self.protocol.is_alive.append(False)

            time.sleep(true_interval(interval, start_time))

            # pocka kym je vlajka na posielanie znovu nastavena
            self.protocol.keep_alive_flag.wait()

        print(f"connection lost in {time.monotonic() - start_time - 15}")


def true_interval(interval, start):
    return interval - (time.monotonic() - start) % interval


def main():
    # todo znovu povolit vyber

    HOST = '127.0.0.1'  # input("Zadaj cieľovú adresu")
    # HOST = '147.175.160.168'
    PORT = 9053  # int(input("Zadaj cieľový port")

    is_file = 0
    # is_file = int(input(
    #     ("Vyber si typ komunikacie:\n"
    #      "   0   -   sprava\n"
    #      "   1   -   subor\n")))
    if is_file == 1:
        # file_name = input("zadaj absolutnu cestu k suboru: ")
        file_name = "C:\\Users\\patri\\pks\\zad_2\\pks_test.txt"
        with open(file_name) as file:
            message = file.read()

        # z file_name odrezeme obsah po poslednu uvodzovku
        file_name = file_name[len(file_name) - file_name[::-1].index("\\"):]
    else:
        file_name = None
        # message = input("Zadaj spravu ktoru chces poslat:\n")
        message = """\
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Curabitur interdum nulla ornare, rutrum purus id, imperdiet libero. Curabitur eros lectus, blandit vitae justo malesuada, lacinia vulputate nisl. Maecenas et neque vitae neque imperdiet tempor id vel magna. Fusce magna neque, viverra a urna nec, egestas varius ex. Quisque vitae viverra massa. Proin lobortis facilisis metus vel semper. Duis cursus pulvinar euismod. Ut rhoncus porta nibh, a placerat velit commodo vel. Morbi ac urna dui. Nunc iaculis elementum odio et efficitur. Praesent bibendum eros eget neque bibendum ultrices sed sit amet est. Quisque venenatis turpis vel magna vestibulum convallis ac id erat. Donec fringilla eu ex cursus hendrerit. Nam lacinia a diam at blandit. Vestibulum et orci laoreet, eleifend tortor ut, faucibus ex.
Donec vel imperdiet tellus, et bibendum augue. Curabitur non sodales est. Donec imperdiet dictum felis a blandit. Donec dictum et nibh ac pretium. Donec placerat porta turpis, convallis elementum lorem fringilla tristique. Donec luctus elementum gravida. Nam eget metus eros. Maecenas nec porta risus. Maecenas vitae purus tincidunt nulla tempor congue ac et erat.
Phasellus tempor vitae sapien ut finibus. Donec lectus urna, dignissim sed nunc ut, tincidunt finibus nulla. Sed venenatis erat et facilisis iaculis. Fusce convallis justo eu lectus consequat sagittis eu vel nulla. Sed nec pharetra neque, eu sodales lectus. Duis tristique nec tellus ac pharetra. Nulla sapien leo, sagittis in posuere non, consequat in lorem. Pellentesque eu pellentesque velit. In odio arcu, maximus et pulvinar at, ullamcorper eget dui.
Pellentesque porta ligula nec metus rhoncus efficitur. Quisque et est laoreet, facilisis diam a, faucibus tellus. Nam vel accumsan est. Aenean eu aliquet lorem. Duis et mi ornare, feugiat justo tempor, vulputate tellus. Suspendisse pharetra tellus a nulla iaculis, eget euismod felis malesuada. Proin ut pretium quam, quis fringilla ante. Donec sit amet metus vel massa aliquet luctus. Vestibulum lorem dui, efficitur at feugiat quis, sodales ut mi. Cras tincidunt tempus sapien, vitae ultricies tellus pharetra eget. In lectus felis, scelerisque nec volutpat et, posuere vitae ligula. Nulla ligula odio, ullamcorper sit amet sem sed, convallis mollis tortor. Pellentesque ultrices placerat ligula in condimentum. Integer cursus fringilla arcu at varius. In lobortis eget lectus vel ornare.
Nulla pulvinar faucibus velit. Phasellus eget urna eu tellus lacinia mollis. Mauris malesuada iaculis faucibus. Sed dignissim egestas purus eu aliquet. Proin rhoncus vestibulum dolor, nec malesuada libero posuere et. Cras elementum diam et lectus finibus pharetra. Donec hendrerit lectus accumsan lectus luctus condimentum. Nulla posuere efficitur mi, id placerat nulla posuere vitae. In eu diam congue, tempus nisl vel, lobortis leo. Morbi malesuada fermentum felis sed interdum. Vivamus eleifend tellus vel turpis rhoncus varius eu ac massa. Integer quis dolor non dui congue semper. Phasellus et libero dictum, imperdiet tortor nec, auctor justo. Aliquam molestie urna sit amet mi ultricies accumsan id sed leo. Pellentesque quis leo at dui bibendum efficitur. Nullam mollis justo at congue efficitur.
koniec"""
    s = Sender(host=HOST, port=PORT, message=message, file_name=file_name)
    s.init_comm()

    # p1 = threading.Thread(target=keepAlive, daemon=True, args=(src_socket, dest_socket))
    # p1.start()

    # pred odoslanim        max velkost je 1500 - 20 (IP) - 8 (UDP) - 4 (velkosť našej hlavičky)
    # max velkost?   508 alebo 1468  - 508 minus hlavicka = 504


if __name__ == "__main__":
    main()
