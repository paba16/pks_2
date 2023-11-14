def CRC(data):
    checksum = int.from_bytes(data, byteorder="big") << 16
    divisor = int("0x18005", 16)

    while (checksum >> 16) > 0:
        most_significant_bit = 1 << checksum.bit_length()

        while (checksum & most_significant_bit) == 0:
            most_significant_bit >>= 1
        checksum ^= divisor << (most_significant_bit.bit_length() - 17)

    return checksum
