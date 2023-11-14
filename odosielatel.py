import socket
import threading
import time
import selectors

def main():
    HOST = '127.0.0.1'  # input("Zadaj cieľovú adresu")
    PORT = 9090  # int(input("Zadaj cieľový port")

    CLIENT_HOST = "127.0.0.1"
    # CLIENT_PORT =
    # typ = int(input(
    #     ("Vyber si typ komunikacie:\n"
    #      "   0   -   subor\n"
    #      "   1   -   sprava\n")))

    # if typ == 0:
    #     file_name = input("zadaj absolutnu cestu k suboru: ")
    # else:
    #     message = input("Zadaj spravu ktoru chces poslat:\n")

    message = """\
Lorem ipsum dolor sit amet, consectetur adipiscing elit. Curabitur interdum nulla ornare, rutrum purus id, imperdiet libero. Curabitur eros lectus, blandit vitae justo malesuada, lacinia vulputate nisl. Maecenas et neque vitae neque imperdiet tempor id vel magna. Fusce magna neque, viverra a urna nec, egestas varius ex. Quisque vitae viverra massa. Proin lobortis facilisis metus vel semper. Duis cursus pulvinar euismod. Ut rhoncus porta nibh, a placerat velit commodo vel. Morbi ac urna dui. Nunc iaculis elementum odio et efficitur. Praesent bibendum eros eget neque bibendum ultrices sed sit amet est. Quisque venenatis turpis vel magna vestibulum convallis ac id erat. Donec fringilla eu ex cursus hendrerit. Nam lacinia a diam at blandit. Vestibulum et orci laoreet, eleifend tortor ut, faucibus ex.
Donec vel imperdiet tellus, et bibendum augue. Curabitur non sodales est. Donec imperdiet dictum felis a blandit. Donec dictum et nibh ac pretium. Donec placerat porta turpis, convallis elementum lorem fringilla tristique. Donec luctus elementum gravida. Nam eget metus eros. Maecenas nec porta risus. Maecenas vitae purus tincidunt nulla tempor congue ac et erat.
Phasellus tempor vitae sapien ut finibus. Donec lectus urna, dignissim sed nunc ut, tincidunt finibus nulla. Sed venenatis erat et facilisis iaculis. Fusce convallis justo eu lectus consequat sagittis eu vel nulla. Sed nec pharetra neque, eu sodales lectus. Duis tristique nec tellus ac pharetra. Nulla sapien leo, sagittis in posuere non, consequat in lorem. Pellentesque eu pellentesque velit. In odio arcu, maximus et pulvinar at, ullamcorper eget dui.
Pellentesque porta ligula nec metus rhoncus efficitur. Quisque et est laoreet, facilisis diam a, faucibus tellus. Nam vel accumsan est. Aenean eu aliquet lorem. Duis et mi ornare, feugiat justo tempor, vulputate tellus. Suspendisse pharetra tellus a nulla iaculis, eget euismod felis malesuada. Proin ut pretium quam, quis fringilla ante. Donec sit amet metus vel massa aliquet luctus. Vestibulum lorem dui, efficitur at feugiat quis, sodales ut mi. Cras tincidunt tempus sapien, vitae ultricies tellus pharetra eget. In lectus felis, scelerisque nec volutpat et, posuere vitae ligula. Nulla ligula odio, ullamcorper sit amet sem sed, convallis mollis tortor. Pellentesque ultrices placerat ligula in condimentum. Integer cursus fringilla arcu at varius. In lobortis eget lectus vel ornare.
Nulla pulvinar faucibus velit. Phasellus eget urna eu tellus lacinia mollis. Mauris malesuada iaculis faucibus. Sed dignissim egestas purus eu aliquet. Proin rhoncus vestibulum dolor, nec malesuada libero posuere et. Cras elementum diam et lectus finibus pharetra. Donec hendrerit lectus accumsan lectus luctus condimentum. Nulla posuere efficitur mi, id placerat nulla posuere vitae. In eu diam congue, tempus nisl vel, lobortis leo. Morbi malesuada fermentum felis sed interdum. Vivamus eleifend tellus vel turpis rhoncus varius eu ac massa. Integer quis dolor non dui congue semper. Phasellus et libero dictum, imperdiet tortor nec, auctor justo. Aliquam molestie urna sit amet mi ultricies accumsan id sed leo. Pellentesque quis leo at dui bibendum efficitur. Nullam mollis justo at congue efficitur."""

    dest_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    dest_socket.connect((HOST, PORT))

    src_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    src_socket.bind(("127.0.0.1", 0))
    src_socket.setblocking(False)

    p1 = threading.Thread(target=keepAlive, daemon=True, args=(src_socket, dest_socket))
    p1.start()

    # pred odoslanim        max velkost je 1500 - 20 (IP) - 8 (UDP) - 4 (velkosť našej hlavičky)
    # max velkost?   508 alebo 1468
    segmenty = [0]
    i = 0
    while segmenty[-1] < len(message):
        max_velkost_packetu = int(input(f"Zadaj maximálnu veľkosť packetu medzi 1 a 504: "))
        if 0 > max_velkost_packetu:
            max_velkost_packetu = 1
        elif 508 - 4 < max_velkost_packetu:
            max_velkost_packetu = 508 - 4

        segmenty.append(segmenty[-1] + max_velkost_packetu)
        dest_socket.send(bytes([0, i % 256, 0, 0]) + message[segmenty[-2]: segmenty[-1]].encode("utf-8"))
        # print(message[start:start+max_velkost_packetu])


def keepAlive(src_socket: socket.socket, dest_socket: socket.socket):
    """
    Kazdych interval sekund posle packet s KeepAlive značkou

    Pomocou zvyšku po delení času intervalom zaisťujeme odoslanie v priemere každých interval sekúnd.

    :param dest_socket:
    :return:
    """
    sel = selectors.DefaultSelector()
    sel.register(src_socket, selectors.EVENT_READ, data=None)

    interval = 5
    start_time = time.monotonic()
    while True:
        # start = time.monotonic()
        dest_socket.send(bytes([4, 0, 0, 0]))
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


if __name__ == "__main__":
    main()
