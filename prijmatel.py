import socket
import time
from CyclicRedundancyCheck import CRC


class SelectiveRepeatARQ:
    # todo konst zo suboru
    ACK = 1
    NACK = 1 << 1
    FILE = 1 << 7
    window_size = 8
    buffer_size = 2 * window_size

    def __init__(self):
        self.message = b''
        self.is_file = False  # todo nastavit pri prvom packete

        # buffer na stare spravy
        self.old_window = {i: None for i in range(self.window_size, self.buffer_size)}

        # musime posunut az ked dostaneme nulty packet
        # dict nie je sorted podla keys
        self.current_window = {i: None for i in range(self.window_size)}

    def check(self, frame: bytes):  # todo popracovat na nazvoch...
        header = frame[:4]
        seq = header[1]
        checksum = int.from_bytes(header[2:], byteorder="big")

        data = frame[4:]

        if (checksum ^ CRC(data)) != 0:
            return bytes([self.NACK, seq, 0, 0])

        if self.current_window.get(seq, False) is not False:
            # ak sa datagram nachadza v ocakavanom okne

            # pri prvok datagrame overime ci je sprava subor
            if self.message == b'' and not self.is_file:
                self.is_file = header[0] & self.FILE  # todo zo suboru

            self.current_window[seq] = data
            self.message += data

            i = 0
            first = next(iter(self.current_window))
            last = next(reversed(self.current_window))

            # todo da sa lepsie?
            keys = iter(self.current_window.values())

            # odstrani od prveho retazove acky
            # todo praca na vysvetleniach
            while next(keys) is not None:

                self.old_window.pop((first + i + self.window_size) % self.buffer_size)
                self.old_window[(first + i) % self.buffer_size] = self.current_window.pop((first + i) % self.buffer_size)
                self.current_window[(last + i + 1) % self.buffer_size] = None
                i += 1

                keys = iter(self.current_window.values())

            return bytes([self.ACK, seq, 0, 0])
        else:
            # buffer je 2x okno, najdem packet s number, ak sa rovna, dostane ack, inak nack
            old_data = self.old_window.get(seq)

            if data == old_data:
                return bytes([SelectiveRepeatARQ.ACK, seq, 0, 0])
            else:
                return bytes([SelectiveRepeatARQ.NACK, seq, 0, 0])

    def output(self):
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
    # todo konst zo suboru
    WINDOW_SIZE = 8

    def __init__(self, host, port):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.server.bind((host, port))

        self.arq = SelectiveRepeatARQ()

    def recieve(self):
        while True:
            message, source = self.server.recvfrom(509)  # todo size
            if message[0] & 4:  # todo  bity zo suboru
                # posle spat Keep alive
                self.server.sendto(bytes([4, 0, 0, 0]), source)
                print("KL")
            elif message[0] & 8:  # todo bity zo suboru
                # todo neopakuj kod repeatu
                self.server.sendto(self.arq.check(message), source)

                self.arq.output()
                break
                # todo ukoncili sme komunikaciu?
            else:
                self.server.sendto(self.arq.check(message), source)


def main():
    HOST = '127.0.0.1'
    PORT = 9053  # int(input("Zadaj port komunikácie: "))

    recv = Reciever(HOST, PORT)
    recv.recieve()


if __name__ == "__main__":
    main()
