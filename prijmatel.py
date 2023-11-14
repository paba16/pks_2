import socket
import time


class SelectiveRepeatARQ:
    window_size = 128
    max_seq = 255

    def __init__(self):
        self.buffer = [None for i in range(2 * self.window_size)]
        self.expected_seq = 0

    def CRC(self, data):
        checksum = int.from_bytes(data, byteorder="big") << 16
        divisor = int("0x18005", 16)

        while (checksum >> 16) > 0:
            most_significant_bit = 1 << checksum.bit_length()

            while (checksum & most_significant_bit) == 0:
                most_significant_bit >>= 1
            checksum ^= divisor << (most_significant_bit.bit_length() - 17)

        return checksum

    def buffer(self, frame: bytes):
        header = frame[:4]
        data = frame[4:]
        checksum = int.from_bytes(header[2:], byteorder="big")

        if (checksum ^ self.CRC(data)) != 0:
            # todo nack after window?
            return

        seq = int.from_bytes(header[1], byteorder="big")
        # if self.window_size <= self.expected_seq < 2 * self.window_size:
        if self.window_size <= seq < 2 * self.window_size:
            index = seq % (2 * self.window_size)  # todo check
            self.buffer[index] = data.decode("utf-8")

        # elif 0 <= self.expected_seq < self.window_size:
        else:
            print("Dropping out of window size packet")


def main():
    HOST = '127.0.0.1'
    PORT = 9090  # int(input("Zadaj port komunikácie: "))

    server = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server.bind((HOST, PORT))

    # udp nema handshake, rovno ziska packet
    # server.listen()

    while True:
        message, source = server.recvfrom(509)  # todo size
        if message[0] & 4:
            # posle Keep alive a ACK
            # server.sendto(bytes([5,0,0,0]), source)
            print("KL")
        else:
            print(source, message[:4], message[4:].decode("utf-8"))


if __name__ == "__main__":
    main()
