import selectors
import socket
import threading
import time

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

    def check(self, frame: bytes):  # todo popracovat na nazvoch...
        header = frame[:4]
        seq = header[1]
        checksum = int.from_bytes(header[2:], byteorder="big")

        data = frame[4:]

        if (checksum ^ CRC(data)) != 0:
            return bytes([LDProtocol.NACK, seq, 0, 0])

        elif seq in self.current_window:
            if self.window[seq] is not None:
                self.bad_seq(data, seq)
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
                new_current_window_end = (current_window_last + i) % LDProtocol.BUFFER_SIZE

                # vycistime cast buffera pri presune do noveho okna
                self.window[new_current_window_end] = None
                self.current_window.append(new_current_window_end)

            self.fragment_count += 1
            return bytes([LDProtocol.ACK, seq, 0, 0])
        else:
            self.bad_seq(data, seq)

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

        else:
            self.server = sock
            host, port = self.server.getsockname()
            # self.server.bind((host,))
            # print(host, port)
        self.server.bind((host, port))

        self.dest_socket = None

        self.debug = True  # "pokazi" prvy ukoncovaci packet

        self.arq = SelectiveRepeatARQ()

    def send_data(self, data, dest):
        try:
            self.server.sendto(data, dest)
        except socket.error as e:
            print(e)
            print("pokracujeme dalej")

    def comm_init(self):
        while True:
            message, source = self.server.recvfrom(509)
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
                # threading.Thread(target=self.alive_countdown, daemon=True).start()

                return self.recieve()
            else:
                print("prisiel non-START packet...")

    def recieve(self):
        selektor = selectors.DefaultSelector()
        selektor.register(self.server, selectors.EVENT_READ)
        self.server.setblocking(False)

        while any(self.protocol.is_alive):
            # todo spytat sa na velkost?
            #  508 je maximum co urcite nebude fragmentovane
            #    - toto zahrna nasu 4B hlavicku

            # todo ako si ma "zmysliet" ze chce poslat swap?
            events = selektor.select()

            for key, mask in events:
                if mask & selectors.EVENT_READ:
                    message, source = self.server.recvfrom(509)

                    if source != self.dest_socket:
                        print("prisli data od neznameho socketu...:")
                        print(message)

                    elif message[0] & LDProtocol.START:
                        self.send_data(bytes([LDProtocol.START | LDProtocol.ACK, 0, 0, 0]), source)

                    elif message[0] & LDProtocol.KEEP_ALIVE:
                        self.protocol.is_alive[-1] = True

                        # posle spat Keep alive
                        self.send_data(bytes([LDProtocol.KEEP_ALIVE | LDProtocol.ACK, 0, 0, 0]), source)
                        print("recieved Keep Alive")

                    elif message[0] & LDProtocol.SWAP:
                        # todo priprav swap?
                        self.send_data(bytes([LDProtocol.SWAP | LDProtocol.ACK, 0, 0, 0]), source)
                        self.swap()

                    elif message[0] & LDProtocol.FIN:
                        # ak sme dostali FIN, odosielatel uz ukoncil odosielanie
                        print("uspesne ukoncene spojenie")
                        # ukoncili sme spojenie, tak spracujeme spravu
                        self.arq.output()
                        return

                    else:
                        if self.debug:
                            # ak je nastaveny debug, zmeni prvu spravu pre kontrolu CRC
                            message += b"PKS"
                            self.debug = False

                        self.send_data(self.arq.check(message), source)

        print("neuspesne ukoncena komunikacia - zlyhanie Keep Alive")
        self.arq.output()

    def swap(self):
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

        # todo ak mame nieco na recieve, vsetko sa pokazi
        #  2 moznosti
        #   1. vyprazdnit bufffer
        #   2. tu riesime swap od sendera. U sendera nastavime aby iba cital
        #       ak nema co citat, akceptujeme swap a swapneme
        #       -
        #       swap od nas by znamenal fungovanie nadalej kym nedostaneme SWAP ACK
        #       na strane odosielatela by sme iba spracovali vsetky odpovede a poslali SWAP ACP a swapli

        novy = odosielatel.Sender(message=message, file_name=file_name, sock=self.server.dup())
        novy.send()

    def alive_countdown(self):
        interval = 5
        start_time = time.monotonic()
        while any(self.protocol.is_alive):
            with self.protocol.alive_lock:
                self.protocol.is_alive.pop(0)
                self.protocol.is_alive.append(False)

            time.sleep((interval - (time.monotonic() - start_time) % interval))

            # pocka kym je vlajka na posielanie znovu nastavena
            self.protocol.keep_alive_flag.wait()

        print(f"connection lost in {time.monotonic() - start_time - 15}")


def main():
    HOST = '127.0.0.1'
    # HOST = ""  # na vsetkych adresach
    PORT = 9053  # int(input("Zadaj port komunikácie: "))

    recv = Reciever(host=HOST, port=PORT)
    recv.comm_init()


if __name__ == "__main__":
    main()
