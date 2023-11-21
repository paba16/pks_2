def CRC(data):
    checksum = int.from_bytes(data, byteorder="big") << 16
    divisor = int("0x18005", 16)

    while (checksum >> 16) > 0:
        checksum ^= divisor << (checksum.bit_length() - 17)

    return checksum
