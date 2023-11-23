import threading


class LDProtocol:
    ACK = 1 << 0
    NACK = 1 << 1
    KEEP_ALIVE = 1 << 2
    FIN = 1 << 3
    SWAP = 1 << 4
    FILE = 1 << 7

    WINDOW_SIZE = 8
    BUFFER_SIZE = 2 * WINDOW_SIZE

    def __init__(self, rtt):
        self.rtt = rtt
        self.lock = threading.Lock()
        self.to_resend = []
