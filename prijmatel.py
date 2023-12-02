import socket
import time

from CyclicRedundancyCheck import CRC
from LDProtocol import LDProtocol
import odosielatel

class SelectiveRepeatARQ:
    def __init__(self):
        self.message = b''
        self.is_file = False
        self.start = 0
        self.is_finalized = False
        self.fragment_count = 0

        # buffer na spravy
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

        if seq in self.current_window:
            if self.window[seq] is not None:
                # todo co ak sme uz tento seq prijali?
                # asi ack ak sa rovna, inak nack
                pass
            # ak sa datagram nachadza v ocakavanom okne

            # todo file flag pri zaciatku komunikácie
            #  toto za bude menit pri zmene iniciacie komunikacue
            # pri prvok datagrame overime ci je sprava subor
            if self.message == b'' and not self.is_file:
                self.start = time.monotonic()
                self.is_file = header[0] & LDProtocol.FILE

            self.current_window[seq] = data
            self.message += data

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
                self.current_window.pop(0)
                new_current_window_end = (current_window_last + i) % LDProtocol.BUFFER_SIZE
                self.window[new_current_window_end] = None
                self.current_window.append(new_current_window_end)

            self.fragment_count += 1
            return bytes([LDProtocol.ACK, seq, 0, 0])
        else:
            # buffer je 2x okno, najdem packet s number, ak sa rovna, dostane ack, inak nack
            old_data = self.window.get(seq)

            if data == old_data:
                return bytes([LDProtocol.ACK, seq, 0, 0])
            else:
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
    def __init__(self, host=None, port=None, sock=None):
        if sock is None:
            self.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        else:
            self.server = sock
        self.server.bind((host, port))

        self.debug = True  # "pokazi" prvy ukoncovaci packet

        self.arq = SelectiveRepeatARQ()

    def recieve(self):
        while not (self.arq.is_finalized and self.arq.is_buffer_empty()):
            # todo spytat sa na velkost?
            #  508 je maximum co urcite nebude fragmentovane
            #    - toto zahrna nasu 4B hlavicku

            # todo ako si ma "zmysliet" ze chce poslat swap?
            message, source = self.server.recvfrom(509)

            if message[0] & LDProtocol.KEEP_ALIVE:
                # todo is_alive u prijemcu?
                # posle spat Keep alive
                self.server.sendto(bytes([LDProtocol.KEEP_ALIVE | LDProtocol.ACK, 0, 0, 0]), source)
                print("recieved Keep Alive")
            elif message[0] & LDProtocol.SWAP:
                self.server.sendto(bytes([LDProtocol.SWAP | LDProtocol.ACK, 0, 0, 0]), source)

                message = "swapped message"
                # todo ak mame nieco na recieve, vsetko sa pokazi
                #  2 moznosti
                #   1. vyprazdnit bufffer
                #   2. tu riesime swap od sendera. U sendera nastavime aby iba cital
                #       ak nema co citat, akceptujeme swap a swapneme
                #       -
                #       swap od nas by znamenal fungovanie nadalej kym nedostaneme SWAP ACK
                #       na strane odosielatela by sme iba spracovali vsetky odpovede a poslali SWAP ACP a swapli

                # ip mam, je to source
                novy = odosielatel.Sender(host=source[0], port=source[1], message=message, sock=self.server.dup())
                novy.send()
            elif message[0] & LDProtocol.FIN:
                if self.debug:
                    # ak je nastaveny debug, zmeni prvu spravu pre kontrolu CRC
                    message += b"PKS"
                    self.debug = False

                # preverime ci je packet spravny
                response = self.arq.check(message)
                if response[0] & LDProtocol.ACK:
                    # nastavime koncovu vlajku iba ak sme spravu prijali
                    self.arq.is_finalized = True

                self.server.sendto(response, source)
            else:
                self.server.sendto(self.arq.check(message), source)

        # ukoncili sme spojenie, tak spracujeme spravu
        self.arq.output()


def main():
    HOST = '127.0.0.1'
    # HOST = ""  # na vsetkych adresach
    PORT = 9053  # int(input("Zadaj port komunikácie: "))

    recv = Reciever(HOST, PORT)
    recv.recieve()


if __name__ == "__main__":
    main()
