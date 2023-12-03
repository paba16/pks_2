divisor = 0x18005


def CRC(data):
    checksum = 0

    for byte in data:
        checksum ^= byte << 8
        for i in range(8):
            if (checksum & 0x8000) == 0:
                checksum <<= 1
            else:
                checksum = (checksum << 1) ^ divisor

    return checksum


def make(data):
    return int.from_bytes(data, byteorder="big") << 16


def question(checksum):
    return (checksum >> 16) > 0
