import threading


class LDProtocol:
    ACK = 1 << 0
    NACK = 1 << 1
    KEEP_ALIVE = 1 << 2
    FIN = 1 << 3
    SWAP = 1 << 4
    START = 1 << 6
    FILE = 1 << 7

    WINDOW_SIZE = 8
    BUFFER_SIZE = 2 * WINDOW_SIZE

    def __init__(self, rtt):
        self.rtt = rtt
        self.sent_swap = False
        self.prepare_swap = False

        self.resend_lock = threading.Lock()
        self.to_resend = []

        self.keep_alive_flag = threading.Event()
        # nastavi vlajku na posielanie Keep Alive
        self.keep_alive_flag.set()

        self.alive_lock = threading.Lock()

        # urcuje na kolko Keep Alive musi zlyhat na ukoncenie spojenia
        # pri kontrole moze byt posledny packet este bez odpovede
        self.is_alive = [True] * 10
