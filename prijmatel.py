import selectors
import select
import socket
import threading
import time
import sys

from CyclicRedundancyCheck import CRC
from LDProtocol import LDProtocol
import odosielatel


class SelectiveRepeatARQ:
    def __init__(self):
        self.message = b''
        self.is_file = False
        self.start = time.monotonic()
        self.is_finalized = False
        self.fragment_count = 0

        # buffer na spravy
        # dict ma moznost vratenia default hodnoty
        self.window = {i: None for i in range(LDProtocol.BUFFER_SIZE)}

        # oznacenie ktore spravy patria do aktualneho okna
        self.current_window = [i for i in range(LDProtocol.WINDOW_SIZE)]

    def is_buffer_empty(self):
        return all(self.window[i] is None for i in self.current_window)

    def check(self, frame: bytes):
        header = frame[:4]
        seq = header[1]
        checksum = int.from_bytes(header[2:], byteorder="big")

        data = frame[4:]

        if (checksum ^ CRC(header[:2] + data)) != 0:
            return bytes([LDProtocol.NACK, seq, 0, 0])

        elif seq in self.current_window:
            if self.window[seq] is not None:
                return self.bad_seq(data, seq)
            # ak sa datagram nachadza v ocakavanom okne

            self.window[seq] = data

            current_window_last = self.current_window[-1]
            to_delete = 0

            # najde dlzku retazca prijatych packetov od prveho v aktualnom okne
            for i in self.current_window:
                if self.window[i] is None:
                    break
                to_delete += 1

            # vsetky tieto packety ponechame v neaktivnej casti okna
            # od najstarsieho packetu v starom okne
            for i in range(to_delete):
                # ulozime najnovsiu spravu z okna
                self.message += self.window[self.current_window.pop(0)]
                new_current_window_end = (current_window_last + i+1) % LDProtocol.BUFFER_SIZE

                # vycistime cast buffera pri presune do noveho okna
                self.window[new_current_window_end] = None
                self.current_window.append(new_current_window_end)

            self.fragment_count += 1
            return bytes([LDProtocol.ACK, seq, 0, 0])
        else:
            return self.bad_seq(data, seq)

    def bad_seq(self, data, seq):
        """
        v pripade zleho cisla spravy overime ci je sprava rovna sprave s rovnakym seq v buffery

        vyuzitie:
         - pride sprava mimo aktualneho okna
         - pride sprava v aktualnom okne, so seq ktory uz mame prijaty

        :param data: sprava
        :param seq: poradove cislo
        :return: odpoved na spravu
        """
        if data == self.window.get(seq):
            # ak ano posleme ACK
            return bytes([LDProtocol.ACK, seq, 0, 0])
        else:
            # inak posleme nack
            return bytes([LDProtocol.NACK, seq, 0, 0])

    def output(self):
        print(f"Subor preneseny za {time.monotonic() - self.start} s")
        if self.is_file:
            separator = self.message.find(b'\x00')

            cesta = input("zadaj absolutnu cestu cieloveho adresara: ")
            filename = self.message[:separator].decode("utf-8")
            text = self.message[separator+1:].decode("utf-8")
            with open(cesta + filename, "w") as txt:
                txt.write(text)
        else:
            print(self.message.decode("utf-8"))


class Reciever:
    def __init__(self, host=None, port=None, sock=None, protocol=LDProtocol(5)):
        self.protocol = protocol

        if sock is None:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.server.bind((host, port))
        else:
            self.server = sock

        self.dest_socket = None

        self.debug = True  # "pokazi" prvy ukoncovaci packet

        self.alive_thread = threading.Thread(target=self.alive_countdown, daemon=True)
        self.arq = SelectiveRepeatARQ()

    def send_data(self, data, dest):
        try:
            self.server.sendto(data, dest)
        except socket.error as e:
            print(e)
            print("pokracujeme dalej")

    def comm_init(self):
        while True:
            message, source = self.server.recvfrom(1473)
            if message[0] & LDProtocol.START:
                print("prijatie ziadosti o zaciatok")
                if message[0] & LDProtocol.FILE:
                    # sprava bude subor
                    self.arq.is_file = True

                # zapamatame si socket s ktorym komunikujeme
                self.dest_socket = source
                # odosle naspat START ACK
                self.send_data(bytes([LDProtocol.START | LDProtocol.ACK, 0, 0, 0]), source)

                # zapneme odpocitavanie Keep Alive
                # self.alive_thread.start() # todo

                return self.recieve()
            else:
                print("prisiel non-START packet...")

    def recieve(self):
        self.swap_thread.start()

        selektor = selectors.DefaultSelector()
        selektor.register(self.server, selectors.EVENT_READ)
        self.server.setblocking(False)

        mask = 0
        while any(self.protocol.is_alive):
            events = selektor.select(timeout=0)

            for key, mask in events:
                if mask & selectors.EVENT_READ:
                    message, source = self.server.recvfrom(1473)

                    if source != self.dest_socket:
                        print("prisli data od neznameho socketu...:")
                        print(message)

                    elif message[0] & LDProtocol.START:
                        self.send_data(bytes([LDProtocol.START | LDProtocol.ACK, 0, 0, 0]), source)

                    elif message[0] & LDProtocol.KEEP_ALIVE:
                        self.protocol.is_alive[-1] = True

                        # posle spat Keep alive
                        self.send_data(bytes([LDProtocol.KEEP_ALIVE | LDProtocol.ACK, 0, 0, 0]), source)

                    elif message[0] & LDProtocol.SWAP:
                        # ak dostaneme packet so značkou swap, začneme sa pripravovať na swap
                        # nezáleží, čí ide o swap alebo swap ack
                        # ak sa nám nepodarí čítanie v následujúcom cykle, prepneme
                        self.protocol.prepare_swap = True

                    elif message[0] & LDProtocol.FIN:
                        # ak sme dostali FIN, odosielatel uz ukoncil odosielanie
                        print("uspesne ukoncene spojenie")
                        # ukoncili sme spojenie, tak vypneme Keep Alive
                        self.protocol.keep_alive_flag.clear()
                        # a vypiseme subor
                        self.arq.output()
                        return

                    elif message[0] == 0 and not (self.protocol.sent_swap or self.protocol.prepare_swap):
                        # ak nie su nastavene ziadne znacky, povazujeme packet za datovy
                        if self.debug:
                            # ak je nastaveny debug, zmeni prvu spravu pre kontrolu CRC
                            message += b"PKS"
                            self.debug = False

                        response = self.arq.check(message)
                        # debug vypise cislo packetu a ci bol uspesne prijaty
                        # if response[0] & LDProtocol.ACK:
                        #     print(f"good: {message[1]}")
                        #     pass
                        # else:
                        #     print(f"bad:  {message[1]}")

                        self.send_data(response, source)

            # ak sme ziadny packet neprijali, swapneme
            if not (mask & selectors.EVENT_READ) and self.protocol.prepare_swap:
                # ak sme neposlali swap request, odosleme swap ack
                if not self.protocol.sent_swap:
                    self.send_data(bytes([LDProtocol.SWAP | LDProtocol.ACK, 0, 0, 0]), self.dest_socket)

                self.swap()

            # selektor na input
            read, _, _ = select.select([sys.stdin], [], [], 0)

            # ak uz pripravujeme swap, neodosleme iny swap request
            if read and not (self.protocol.prepare_swap or self.protocol.sent_swap):
                sys.stdin.readline()

                self.protocol.sent_swap = True
                self.send_data(bytes([LDProtocol.SWAP, 0, 0, 0]), self.dest_socket)



        print("neuspesne ukoncena komunikacia - zlyhanie Keep Alive")
        self.arq.output()

    def swap(self):
        self.protocol.keep_alive_flag.clear()

        is_file = int(input(
            ("Vyber si typ komunikacie:\n"
             "   0   -   sprava\n"
             "   1   -   subor\n")))
        if is_file == 1:
            # file_name = input("zadaj absolutnu cestu k suboru: ")
            file_name = "C:\\Users\\patri\\pks\\zad_2\\pks_test.txt"
            with open(file_name) as file:
                message = file.read()

            # z file_name odrezeme obsah po poslednu uvodzovku
            file_name = file_name[len(file_name) - file_name[::-1].index("\\"):]
        else:
            file_name = None
            message = input("Zadaj spravu ktoru chces poslat:\n")

        host, port = self.dest_socket
        novy = odosielatel.Sender(host=host, port=port, message=message, file_name=file_name, sock=self.server.dup())
        novy.send()

        self.protocol.prepare_swap = False
        self.protocol.sent_swap = False
        self.protocol.keep_alive_flag.set()

    def alive_countdown(self):
        interval = 5
        start_time = time.monotonic()
        while any(self.protocol.is_alive) and self.protocol.keep_alive_flag.is_set():
            with self.protocol.alive_lock:
                self.protocol.is_alive.pop(0)
                self.protocol.is_alive.append(False)
            # print(self.protocol.is_alive)

            # pocka kym je vlajka na posielanie nastavena
            if self.protocol.keep_alive_flag.wait():
                time.sleep((interval - (time.monotonic() - start_time) % interval))

        if not any(self.protocol.is_alive):
            print(f"connection lost in {time.monotonic() - start_time - 15}")


def main():
    HOST = ""  # pocuva na vsetkych adresach
    PORT = 9054
    # PORT = int(input("Zadaj port komunikácie")
    # while not (1024 < PORT < 65536):
    #     PORT = int(input("Zadaj port komunikácie")

    recv = Reciever(host=HOST, port=PORT)
    recv.comm_init()


if __name__ == "__main__":
    main()
