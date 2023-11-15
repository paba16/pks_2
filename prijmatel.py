import socket
import time
from CyclicRedundancyCheck import CRC


class SelectiveRepeatARQ:
    window_size = 128
    max_seq = 255

    def __init__(self):
        self.message = b''
        self.buffer = [None for i in range(2 * self.window_size)]
        self.is_file = False  # todo nastavit pri prvom packete
        self.re = 0
        self.segment = 0

    def buffer(self, frame: bytes):
        header = frame[:4]
        data = frame[4:]
        checksum = int.from_bytes(header[2:], byteorder="big")

        if (checksum ^ CRC(data)) != 0:
            # todo nack after window?
            return

        seq = int.from_bytes(header[1], byteorder="big")
        # if self.window_size <= self.expected_seq < 2 * self.window_size:
        if self.window_size * self.segment <= seq < self.window_size * (self.segment + 1):
            index = seq % (2 * self.window_size)  # todo check
            self.buffer[index] = data.decode("utf-8")

        # elif 0 <= self.expected_seq < self.window_size:
        else:
            print("Dropping out of window size packet")

    # def clean_buffer(self, section):
    #     """
    #     clears buffer section, while putting its content into message
    #     :param section: 0 or 1
    #     :return:
    #     """
    #     size = len(self.buffer)
    #     for i in range(size * section, size * (section + 1)):
    #         self.message += self.buffer[i]
    #         self.buffer[i] = None

    def output(self):
        if self.is_file:
            separator = self.message.find(b'\x00')

            cesta = input("zadaj absolutnu cestu cieloveho adresara: ")
            filename = self.message[:separator].decode("utf-8")
            text = self.message[separator+1:].decode("utf-8")
            with open(cesta + filename, "w") as txt:
                txt.write(text)
            pass
        else:
            print(self.message.decode("utf-8"))



def main():
    HOST = '127.0.0.1'
    PORT = 9052  # int(input("Zadaj port komunikácie: "))

    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind((HOST, PORT))

    # udp nema handshake, rovno ziska packet
    # server.listen()
    # a = SelectiveRepeatARQ()
    while True:
        message, source = server.recvfrom(509)  # todo size
        if message[0] & 4:
            # posle Keep alive a ACK
            # server.sendto(bytes([5,0,0,0]), source)
            print("KL")
        else:
            print(message)
            print(source, message[:4], message[4:].decode("utf-8"))


if __name__ == "__main__":
    main()
