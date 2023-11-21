import socket
import time

from CyclicRedundancyCheck import CRC
from odosielatel import Sender
from LDProtocol import LDProtocol

class SelectiveRepeatARQ:
    def __init__(self):
        self.message = b''
        self.is_file = False
        self.start = 0

        # dict nie je sorted podla keys
        # buffer na stare spravy
        self.old_window = {i: None for i in range(LDProtocol.WINDOW_SIZE, LDProtocol.BUFFER_SIZE)}

        # musime posunut az ked dostaneme nulty packet
        self.current_window = {i: None for i in range(LDProtocol.WINDOW_SIZE)}

    def check(self, frame: bytes):  # todo popracovat na nazvoch...
        header = frame[:4]
        seq = header[1]
        checksum = int.from_bytes(header[2:], byteorder="big")

        data = frame[4:]

        if (checksum ^ CRC(data)) != 0:
            return bytes([LDProtocol.NACK, seq, 0, 0])

        if self.current_window.get(seq, False) is not False:
            # ak sa datagram nachadza v ocakavanom okne

            # pri prvok datagrame overime ci je sprava subor
            if self.message == b'' and not self.is_file:
                self.start = time.monotonic()
                self.is_file = header[0] & LDProtocol.FILE

            self.current_window[seq] = data
            self.message += data

            i = 0
            first = next(iter(self.current_window))
            last = next(reversed(self.current_window))

            # todo treba lepsie?
            keys = iter(self.current_window.values())

            # odstrani od prveho retazove acky
            # todo praca na vysvetleniach
            while next(keys) is not None:

                self.old_window.pop((first + i + LDProtocol.WINDOW_SIZE) % LDProtocol.BUFFER_SIZE)
                self.old_window[(first + i) % LDProtocol.BUFFER_SIZE] = (
                    self.current_window.pop((first + i) % LDProtocol.BUFFER_SIZE))
                self.current_window[(last + i + 1) % LDProtocol.BUFFER_SIZE] = None
                i += 1

                keys = iter(self.current_window.values())

            return bytes([LDProtocol.ACK, seq, 0, 0])
        else:
            # buffer je 2x okno, najdem packet s number, ak sa rovna, dostane ack, inak nack
            old_data = self.old_window.get(seq)

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
    def __init__(self, host, port):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server.bind((host, port))

        self.arq = SelectiveRepeatARQ()

    def recieve(self):
        while True:
            message, source = self.server.recvfrom(509)  # todo size
            if message[0] & LDProtocol.KEEP_ALIVE:  # todo  bity zo suboru
                # posle spat Keep alive
                self.server.sendto(bytes([LDProtocol.KEEP_ALIVE | LDProtocol.ACK, 0, 0, 0]), source)
                print("KL")
            # elif message[0] & LDProtocol.SWAP:
                # message = "ok".encode("utf-8")

                # todo ako toto funguje?
                #  ziskam ip od spravy ktoru ziskam?
                #  od koho ma prist SWAP?
                # Sender(host=self.host, port=self.port, message=message, sock=self.server.dup())
            elif message[0] & LDProtocol.FIN:
                # todo neopakuj kod repeatu
                self.server.sendto(self.arq.check(message), source)

                # todo kod co zaruci ze mame vsetky packety
                #  cez kontrolu buffera

                self.arq.output()
                break
                # todo neukoncili sme komunikaciu
                #  este treba overit ci je buffer prazdny
            else:
                self.server.sendto(self.arq.check(message), source)


def main():
    # HOST = '127.0.0.1'
    HOST = '147.175.160.168'
    PORT = 9053  # int(input("Zadaj port komunikácie: "))

    recv = Reciever(HOST, PORT)
    recv.recieve()


if __name__ == "__main__":
    main()
