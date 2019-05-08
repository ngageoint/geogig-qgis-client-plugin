# reads size - will return 0 if there's a problem (i.e. at end-of-file)
# raw = reader
def readSize(raw):
    try:
        return readUnsignedVarLong(raw)
    except:
        return 0

# converted from GeoGig Varint#readUnsignedVarLong
def readUnsignedVarLong(raw):
    value = 0
    i = 0
    while True:
        b = raw.read(1)[0]
        if (b & 0x80) == 0:
            return value | (b<<i)
        value |= (b & 0x7F) << i
        i += 7
        if i>63:
            raise Exception( "Variable length quantity is too long (must be <= 63)")

