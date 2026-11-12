CFLAGS += -Wall -Wextra -g $(shell pkg-config --cflags pappl)
LDLIBS += $(shell pkg-config --libs pappl)
all: niimbot-ipp
niimbot-ipp: service.c
	$(CC) $(CFLAGS) -o $@ $< $(LDLIBS)
clean:
	rm -f niimbot-ipp
