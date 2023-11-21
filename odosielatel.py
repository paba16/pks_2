import socket
import threading
import time
import selectors

from LDProtocol import LDProtocol
from CyclicRedundancyCheck import CRC

resend_lock = threading.Lock()
to_resend = []


class Packet:
    RTT = 5  # todo menit?

    def __init__(self, flags, number, message):
        self.flags = flags
        self.number = number  # poradie % LDProtocol.WINDOW_SIZE
        self.checksum = CRC(message)
        self.message = message

        self.ack = False

        self.timer = threading.Timer(Packet.RTT, self.reschedule)
    
    def reschedule(self):
        """
        Vytvori novy casovac a prida datagram ku packetom na znovu odoslanie
        :return:
        """
        global to_resend
        self.timer = threading.Timer(Packet.RTT, self.reschedule)

        with resend_lock:
            to_resend.append(self)

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
    def __init__(self, host=None, port=None, message=None, is_file=None, file_name=None, sock=None):
        self.message = self.construct_message(file_name, message)
        self.last_sent_index = 0

        self.is_file = is_file

        # pri inicializacii mame packet oznacujuci zaciatok spravy na 0. byte
        self.datagrams = []

        if sock is None:
            self.comm_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        else:
            self.comm_socket = sock

        self.comm_socket.connect((host, port))
        self.comm_socket.setblocking(False)

        self.selector = selectors.DefaultSelector()
        self.selector.register(self.comm_socket, selectors.EVENT_WRITE | selectors.EVENT_READ)

        self.is_alive = [True] * 3

        self.alive_thread = threading.Thread(target=self.keep_alive)
        self.send_keep_alive = threading.Event()

        # nastavi vlajku na fungovanie a spusti
        self.send_keep_alive.set()
        self.alive_thread.start()

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

    def send(self):
        packet_size = 500  # todo packet size
        i = 0

        # todo casovac pouziva RTT, asi ziskany z Keep Alive
        #  rtt viem zistit aj z ack/nack

        # todo while loop neposle outstanding resend packets
        #  neriesi exit ak nie sme alive
        while self.last_sent_index < len(self.message):
            events = self.selector.select()
            for key, mask in events:
                if mask & selectors.EVENT_READ:
                    conn = key.fileobj

                    # dostaneme naspat hlavicku s nulovym checksum
                    message = conn.recv(4)

                    if message[0] & LDProtocol.ACK:
                        # zistime ktory packet z okna sme prijali
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

                        # todo upravit RTT
                    elif message[0] & LDProtocol.NACK:
                        # zistime ktory packet z okna sme prijali
                        k = self.get_number_packet(message[1])
                        packet = self.datagrams[k]

                        packet.stop_timer()
                        packet.reschedule()

                        # todo upravit RTT
                    elif message[0] & LDProtocol.KEEP_ALIVE:
                        self.is_alive[-1] = True
                        # todo kde exit ak nie sme alive?
                        #  check any(self.is_alive) pred odoslanim

                    elif message[0] & LDProtocol.SWAP:
                        # todo pozastavime alive_thread
                        #   zapneme vlastneho prijimatela
                        #   po ukonceni prijimatela znovu zapneme alive_thread
                        # self.send_keep_alive.set()
                        # todo prepneme sa na prijimatela
                        # self.send_keep_alive.clear()
                        pass

                if mask & selectors.EVENT_WRITE:
                    conn = key.fileobj
                    if len(to_resend) != 0:
                        print("resend")
                        # bud preposlem stary segment
                        with resend_lock:
                            item = to_resend.pop(0).out()
                        conn.send(item)

                    elif len(self.datagrams) < LDProtocol.WINDOW_SIZE:
                        # alebo poslem novy
                        flags = 0
                        # print("write", [i.ack for i in self.datagrams])

                        start = self.last_sent_index
                        end = start + packet_size

                        if start == 0 and self.is_file == 1:
                            flags |= LDProtocol.FILE

                        if end >= len(self.message):
                            print("Fin")
                            flags |= LDProtocol.FIN

                        # out of range slicing is handled graceffully
                        # [][999:-999] = [][len([]): -len([])]
                        message = self.message[start:end]

                        self.datagrams.append(Packet(flags, i, message))
                        self.last_sent_index = end

                        conn.send(self.datagrams[-1].out())

                        i = (i + 1) % LDProtocol.BUFFER_SIZE

    def keep_alive(self):
        """
        Kazdych interval sekund posle packet s KeepAlive značkou

        Pomocou zvyšku po delení času intervalom zaisťujeme odoslanie v priemere každých interval sekúnd.

        :return:
        """
        interval = 5
        start_time = time.monotonic()
        while any(self.is_alive):
            # start = time.monotonic()
            self.comm_socket.send(bytes([4, 0, 0, 0]))

            self.is_alive.pop(0)
            self.is_alive.append(False)

            time.sleep((interval - (time.monotonic() - start_time) % interval))

            # print(time.monotonic() - start)

        # todo ako po ukonceni odosielania?
        print(f"connection lost in {time.monotonic() - start_time - 15}")



def main():
    # HOST = '127.0.0.1'  # input("Zadaj cieľovú adresu")
    HOST = '147.175.160.168'
    PORT = 9053  # int(input("Zadaj cieľový port")

    is_file = 1
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
Nulla pulvinar faucibus velit. Phasellus eget urna eu tellus lacinia mollis. Mauris malesuada iaculis faucibus. Sed dignissim egestas purus eu aliquet. Proin rhoncus vestibulum dolor, nec malesuada libero posuere et. Cras elementum diam et lectus finibus pharetra. Donec hendrerit lectus accumsan lectus luctus condimentum. Nulla posuere efficitur mi, id placerat nulla posuere vitae. In eu diam congue, tempus nisl vel, lobortis leo. Morbi malesuada fermentum felis sed interdum. Vivamus eleifend tellus vel turpis rhoncus varius eu ac massa. Integer quis dolor non dui congue semper. Phasellus et libero dictum, imperdiet tortor nec, auctor justo. Aliquam molestie urna sit amet mi ultricies accumsan id sed leo. Pellentesque quis leo at dui bibendum efficitur. Nullam mollis justo at congue efficitur."""
    s = Sender(HOST, PORT, message, is_file, file_name)
    s.send()

    # p1 = threading.Thread(target=keepAlive, daemon=True, args=(src_socket, dest_socket))
    # p1.start()

    # pred odoslanim        max velkost je 1500 - 20 (IP) - 8 (UDP) - 4 (velkosť našej hlavičky)
    # max velkost?   508 alebo 1468  - 508 minus hlavicka = 504


if __name__ == "__main__":
    main()
