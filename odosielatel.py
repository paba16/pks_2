import socket
import threading
import time
import selectors
from CyclicRedundancyCheck import CRC

# todo vsetko prerobit na full-duplex
#  full-duplex - posielanie sprav z oboch stran naraz
#  preba to aj pre ack aj pre KeepAlive pocas posielania packetov
#  pouzit select

resend_lock = threading.Lock()
to_resend = []


class Packet:
    ACK = 1
    NACK = 2
    KEEP_ALIVE = 4
    SWAP = 8
    WINDOW_SIZE = 8

    RTT = 5

    def __init__(self, end_index, flags, number, message, ack=False):
        self.flags = flags
        # poradie packetu, nasledne pouzity zysok po deleni s window_size
        self._number = number
        self.checksum: int = CRC(message)
        self.message = message

        # znaci cast pokial obsahuje text
        self.end_index = end_index
        # iba pre nulty (neodoslany) segment, znaci end_index
        self.ack = ack

        self.timer = threading.Timer(Packet.RTT, self.resend)

    @property
    def number(self):
        return self._number % Packet.WINDOW_SIZE

    @staticmethod
    def file_header(filename, message):
        if filename is None:
            return message.encode("utf-8")
        return filename.encode("utf-8") + bytes([0]) + message.encode("utf-8")
    
    def resend(self):
        global to_resend
        self.timer = threading.Timer(Packet.RTT, self.resend)

        with resend_lock:
            to_resend.append(self)

    def stop_timer(self):
        self.timer.cancel()

    def out(self):
        _out = (bytes([self.flags, self.number])
                + int.to_bytes(self.checksum, length=16, byteorder="big")
                + self.message)
        self.timer.start()
        return _out


class Sender:
    def __init__(self, host, port, own_addr, message, is_file, file_name=None):
        self.message = message
        self.is_file = is_file
        self.file_name = file_name

        self.datagramy = []

        self.dest_port = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.dest_port.connect((host, port))
        self.dest_port.setblocking(False)

        self.src_port = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.src_port.bind((own_addr, 0))  # OS vyberie nas port
        self.src_port.setblocking(False)

        self.vyber = selectors.DefaultSelector()
        self.vyber.register(self.dest_port, selectors.EVENT_WRITE)
        self.vyber.register(self.src_port, selectors.EVENT_READ)
        # todo start Keep Alive
        
    def send(self):
        velkost_packetu = 500

        # todo pridat odosielanie Keep Alive
        # todo casovac pouziva RTT, asi ziskany z Keep Alive
        #  rtt viem zistit aj z ack/nack

        # todo zmenit while loop
        while self.datagramy[-1].end_index < len(self.message):
            events = self.vyber.select()
            for key, mask in events:
                if mask & selectors.EVENT_READ:
                    conn = key.fileobj

                    # dostaneme naspat hlavicku
                    message = conn.recv(velkost_packetu)
                    if message[0] & Packet.ACK:
                        packet = self.datagramy[0]  # todo rozdelit
                        packet.stop_timer()

                        # spocitame pocet packetov za sebou s ACK od prveho
                        j = 0
                        while self.datagramy[j].ack and j < Packet.WINDOW_SIZE:
                            j += 1

                        for k in range(j):
                            self.datagramy.pop(0)

                        # todo odstranit z okna dany prvok
                        #  otazka je ako s prepoctom medzi vecami
                        #

                        # todo upravit RTT
                    elif message[0] & Packet.NACK:

                        packet = self.datagramy[0]  # todo rozdelit
                        packet.stop_timer()
                        packet.resend()
                        # todo check
                        # todo upravit RTT
                    elif message[0] & Packet.KEEP_ALIVE:
                        # todo zapisem do alive pamate
                        pass
                    elif message[0] & Packet.SWAP:
                        # todo zacneme prijimat packety
                        # todo spytat sa presnejsie
                        pass

                elif mask & selectors.EVENT_WRITE:
                    conn = key.fileobj
                    if len(to_resend) == 0:
                        # bud preposlem stary segment
                        with resend_lock:
                            item = to_resend.pop(0)
                        conn.send(item)

                    elif len(self.datagramy) < Packet.WINDOW_SIZE:
                        # alebo poslem novy
                        start = self.datagramy[-1].end_index
                        end = start + velkost_packetu
                        if i == 0:
                            self.datagramy.pop(0)  # odstranime nulty segment
                            if self.is_file:
                                # pri subore vlozime nazov suboru
                                end -= len(self.file_name) + 1
                                message = Packet.file_header(self.file_name, message[:end])

                        self.datagramy.append(Packet(end, self.is_file << 7, i, message))
                        conn.send(self.datagramy[-1])

                        i = (i + 1) % Packet.WINDOW_SIZE

                    # todo nedobre
                    # casovac je threading.Timer, neda sa spustit znovu

    def keepAlive(self):
        # todo prerobit cele
        """
        Kazdych interval sekund posle packet s KeepAlive značkou

        Pomocou zvyšku po delení času intervalom zaisťujeme odoslanie v priemere každých interval sekúnd.

        :param dest_socket:
        :return:
        """
        sel = selectors.DefaultSelector()
        sel.register(self.src_socket, selectors.EVENT_READ, data=None)

        interval = 5
        start_time = time.monotonic()
        while True:
            # start = time.monotonic()
            self.dest_socket.send(bytes([4, 0, 0, 0]))
            # detekuj odpoved
            # popripade zapis neziskanu odpoved
            # ak neziskas odpoved na 3, close connection

            # pri select nastane cakanie do 1 s
            # cakanie je blocking
            # idk ako

            # events = sel.select(timeout=1)
            # for key, mask in events:
            #     dest_socket.recv(508)

            time.sleep((interval - (time.monotonic() - start_time) % interval))

            # print(time.monotonic() - start)


def main():
    HOST = '127.0.0.1'  # input("Zadaj cieľovú adresu")
    PORT = 9052  # int(input("Zadaj cieľový port")

    CLIENT_HOST = "127.0.0.1"
    CLIENT_PORT = 0

    is_file = 0
    # is_file = int(input(
    #     ("Vyber si typ komunikacie:\n"
    #      "   0   -   sprava\n"
    #      "   1   -   subor\n")))
    if is_file == 1:
        file_name = input("zadaj absolutnu cestu k suboru: ")
        with open(file_name) as file:
            message = file.read()
    else:
        file_name = None
        message = input("Zadaj spravu ktoru chces poslat:\n")


    s = Sender(HOST, PORT, CLIENT_HOST, message, is_file, file_name=file_name)


    # p1 = threading.Thread(target=keepAlive, daemon=True, args=(src_socket, dest_socket))
    # p1.start()

    # pred odoslanim        max velkost je 1500 - 20 (IP) - 8 (UDP) - 4 (velkosť našej hlavičky)
    # max velkost?   508 alebo 1468  - 508 minus hlavicka = 504

    i = 0
    window_size = Packet.WINDOW_SIZE

    segmenty = [Packet(0, 0, 0, b'', ack=True)]


if __name__ == "__main__":
    main()
