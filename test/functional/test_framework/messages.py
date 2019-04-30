#!/usr/bin/env python3
# Copyright (c) 2010 ArtForz -- public domain half-a-node
# Copyright (c) 2012 Jeff Garzik
# Copyright (c) 2010-2018 The Bitcoin Core developers
# Distributed under the MIT software license, see the accompanying
# file COPYING or http://www.opensource.org/licenses/mit-license.php.
"""Unit-e test framework primitive and message structures

CBlock, CTransaction, CBlockHeader, CTxIn, CTxOut, etc....:
    data structures that should map to corresponding structures in
    unite/primitives

msg_block, msg_tx, msg_headers, etc.:
    data structures that represent network messages

ser_*, deser_*: functions that handle serialization/deserialization."""
from codecs import encode
from enum import Enum
import copy
import hashlib
from io import BytesIO
import random
import socket
import struct
import time

from test_framework.siphash import siphash256
from test_framework.util import hex_str_to_bytes, bytes_to_hex_str

MIN_VERSION_SUPPORTED = 60001
MY_VERSION = 70014  # past bip-31 for ping/pong
MY_SUBVERSION = b"/python-mininode-tester:0.0.3/"
MY_RELAY = 1 # from version 70001 onwards, fRelay should be appended to version messages (BIP37)

MAX_INV_SZ = 50000
MAX_LOCATOR_SZ = 101
MAX_BLOCK_BASE_SIZE = 1000000

UNIT = 100000000  # 1 btc in satoshis

BIP125_SEQUENCE_NUMBER = 0xfffffffd  # Sequence number that is BIP 125 opt-in and BIP 68-opt-out

NODE_NETWORK = (1 << 0)
# NODE_GETUTXO = (1 << 1)
NODE_BLOOM = (1 << 2)
NODE_WITNESS = (1 << 3)
NODE_NETWORK_LIMITED = (1 << 10)
NODE_SNAPSHOT = (1 << 15)

MSG_TX = 1
MSG_BLOCK = 2
MSG_WITNESS_FLAG = 1 << 30
MSG_TYPE_MASK = 0xffffffff >> 2

# Serialization/deserialization tools
def sha256(s):
    return hashlib.sha256(s).digest()

def ripemd160(s):
    return hashlib.new('ripemd160', s).digest()

def hash256(s):
    return sha256(sha256(s))

def ser_compact_size(l):
    r = b""
    if l < 253:
        r = struct.pack("B", l)
    elif l < 0x10000:
        r = struct.pack("<BH", 253, l)
    elif l < 0x100000000:
        r = struct.pack("<BI", 254, l)
    else:
        r = struct.pack("<BQ", 255, l)
    return r

def deser_compact_size(f):
    nit = struct.unpack("<B", f.read(1))[0]
    if nit == 253:
        nit = struct.unpack("<H", f.read(2))[0]
    elif nit == 254:
        nit = struct.unpack("<I", f.read(4))[0]
    elif nit == 255:
        nit = struct.unpack("<Q", f.read(8))[0]
    return nit

def deser_string(f):
    nit = deser_compact_size(f)
    return f.read(nit)

def ser_string(s):
    return ser_compact_size(len(s)) + s

def deser_uint32(f):
    return struct.unpack("<I", f.read(4))[0]

def deser_uint64(f):
    return struct.unpack("<Q", f.read(8))[0]

def deser_uint256(f):
    r = 0
    for i in range(8):
        t = deser_uint32(f)
        r += t << (i * 32)
    return r

def ser_uint32(u):
    return struct.pack("<I", u & 0xFFFFFFFF)

def ser_uint64(u):
    return struct.pack("<Q", u & 0xFFFFFFFFFFFFFFFF)

def ser_uint256(u):
    return int(u).to_bytes(32, 'little')


def uint256_from_str(s):
    return int.from_bytes(s[:32], 'little')


def uint256_from_compact(c):
    nbytes = (c >> 24) & 0xFF
    v = (c & 0xFFFFFF) << (8 * (nbytes - 3))
    return v


def deser_vector(f, c):
    nit = deser_compact_size(f)
    r = []
    for i in range(nit):
        t = c()
        t.deserialize(f)
        r.append(t)
    return r


# ser_function_name: Allow for an alternate serialization function on the
# entries in the vector (we use this for serializing the vector of transactions
# for a witness block).
def ser_vector(l, ser_function_name=None):
    r = ser_compact_size(len(l))
    for i in l:
        if ser_function_name:
            r += getattr(i, ser_function_name)()
        else:
            r += i.serialize()
    return r


def deser_uint32_map(f, klass):
    m = dict()
    size = deser_compact_size(f)
    for _ in range(size):
        k = struct.unpack('<I', f.read(4))[0]
        o = klass()
        o.deserialize(f)
        m[k] = o
    return m


def ser_uint32_map(d):
    r = ser_compact_size(len(d))
    for i in d:
        r += struct.pack('<I', i)
        r += d[i].serialize()
    return r


def deser_uint256_vector(f):
    nit = deser_compact_size(f)
    r = []
    for i in range(nit):
        t = deser_uint256(f)
        r.append(t)
    return r


def ser_uint256_vector(l):
    r = ser_compact_size(len(l))
    for i in l:
        r += ser_uint256(i)
    return r


def deser_string_vector(f):
    nit = deser_compact_size(f)
    r = []
    for i in range(nit):
        t = deser_string(f)
        r.append(t)
    return r


def ser_string_vector(l):
    r = ser_compact_size(len(l))
    for sv in l:
        r += ser_string(sv)
    return r


# Deserialize from a hex string representation (eg from RPC)
def FromHex(obj, hex_string):
    obj.deserialize(BytesIO(hex_str_to_bytes(hex_string)))
    return obj

# Convert a binary-serializable object to hex (eg for submission via RPC)
def ToHex(obj):
    return bytes_to_hex_str(obj.serialize())

# Objects that map to unit-e objects, which can be serialized/deserialized

class CAddress():
    def __init__(self):
        self.time = 0
        self.nServices = 1
        self.pchReserved = b"\x00" * 10 + b"\xff" * 2
        self.ip = "0.0.0.0"
        self.port = 0

    def deserialize(self, f, with_time=True):
        if with_time:
            self.time = struct.unpack("<i", f.read(4))[0]
        self.nServices = struct.unpack("<Q", f.read(8))[0]
        self.pchReserved = f.read(12)
        self.ip = socket.inet_ntoa(f.read(4))
        self.port = struct.unpack(">H", f.read(2))[0]

    def serialize(self, with_time=True):
        r = b""
        if with_time:
            r += struct.pack("<i", self.time)
        r += struct.pack("<Q", self.nServices)
        r += self.pchReserved
        r += socket.inet_aton(self.ip)
        r += struct.pack(">H", self.port)
        return r

    def __repr__(self):
        return "CAddress(nServices=%i ip=%s port=%i)" % (self.nServices,
                                                         self.ip, self.port)

class CInv():
    typemap = {
        0: "Error",
        1: "TX",
        2: "Block",
        1|MSG_WITNESS_FLAG: "WitnessTx",
        2|MSG_WITNESS_FLAG : "WitnessBlock",
        4: "CompactBlock"
    }

    def __init__(self, t=0, h=0):
        self.type = t
        self.hash = h

    def deserialize(self, f):
        self.type = struct.unpack("<i", f.read(4))[0]
        self.hash = deser_uint256(f)

    def serialize(self):
        r = b""
        r += struct.pack("<i", self.type)
        r += ser_uint256(self.hash)
        return r

    def __repr__(self):
        return "CInv(type=%s hash=%064x)" \
            % (self.typemap[self.type], self.hash)


class CBlockLocator():
    def __init__(self):
        self.nVersion = MY_VERSION
        self.vHave = []

    def deserialize(self, f):
        self.nVersion = struct.unpack("<i", f.read(4))[0]
        self.vHave = deser_uint256_vector(f)

    def serialize(self):
        r = b""
        r += struct.pack("<i", self.nVersion)
        r += ser_uint256_vector(self.vHave)
        return r

    def __repr__(self):
        return "CBlockLocator(nVersion=%i vHave=%s)" \
            % (self.nVersion, repr(self.vHave))


class COutPoint():
    def __init__(self, hash=0, n=0):
        self.hash = hash
        self.n = n

    def deserialize(self, f):
        self.hash = deser_uint256(f)
        self.n = struct.unpack("<I", f.read(4))[0]

    def serialize(self):
        r = b""
        r += ser_uint256(self.hash)
        r += struct.pack("<I", self.n)
        return r

    def is_null(self):
        return self.hash == 0

    def __repr__(self):
        return "COutPoint(hash=%064x n=%i)" % (self.hash, self.n)


class CTxIn():
    def __init__(self, outpoint=None, scriptSig=b"", nSequence=0):
        if outpoint is None:
            self.prevout = COutPoint()
        else:
            self.prevout = outpoint
        self.scriptSig = scriptSig
        self.nSequence = nSequence

    def deserialize(self, f):
        self.prevout = COutPoint()
        self.prevout.deserialize(f)
        self.scriptSig = deser_string(f)
        self.nSequence = struct.unpack("<I", f.read(4))[0]

    def serialize(self):
        r = b""
        r += self.prevout.serialize()
        r += ser_string(self.scriptSig)
        r += struct.pack("<I", self.nSequence)
        return r

    def __repr__(self):
        return "CTxIn(prevout=%s scriptSig=%s nSequence=%i)" \
            % (repr(self.prevout), bytes_to_hex_str(self.scriptSig),
               self.nSequence)


class CTxOut():
    def __init__(self, nValue=0, scriptPubKey=b""):
        self.nValue = int(nValue)
        self.scriptPubKey = scriptPubKey

    def deserialize(self, f):
        self.nValue = struct.unpack("<q", f.read(8))[0]
        self.scriptPubKey = deser_string(f)

    def serialize(self):
        r = b""
        r += struct.pack("<q", self.nValue)
        r += ser_string(self.scriptPubKey)
        return r

    def is_unspendable(self):
        if len(self.scriptPubKey) > 0:
            return self.scriptPubKey[0] == 0x6a or len(self.scriptPubKey) > 10000
        return False


    def __repr__(self):
        return "CTxOut(nValue=%i.%08i scriptPubKey=%s)" \
            % (self.nValue // UNIT, self.nValue % UNIT,
               bytes_to_hex_str(self.scriptPubKey))


class TxType(Enum):
    REGULAR = 0
    COINBASE = 1
    DEPOSIT = 2
    VOTE = 3
    LOGOUT = 4
    SLASH = 5
    WITHDRAW = 6
    ADMIN = 7


class UTXO:
    def __init__(self, height, tx_type, outpoint, tx_out):
        self.outpoint = outpoint
        self.height = height
        self.tx_type = tx_type
        self.txOut = tx_out

    def deserialize(self, f):
        self.outpoint = COutPoint()
        self.outpoint.deserialize(f)
        self.height = struct.unpack("<I", f.read(4))[0]
        self.tx_type = TxType(struct.unpack("<B", f.read[1])[0])
        self.txOut = CTxOut()
        self.txOut.deserialize(f)

    def serialize(self):
        r = b""
        r += self.outpoint.serialize()
        r += struct.pack("<I", self.height)
        r += struct.pack("<B", self.tx_type.value)
        r += self.txOut.serialize()
        return r

    def __repr__(self):
        return "UTXO(outpoint=%s height=%i tx_type=%s txOut=%s)" \
            % (self.outpoint, self.height, self.tx_type.name, repr(self.txOut))


class CScriptWitness():
    def __init__(self):
        # stack is a vector of strings
        self.stack = []

    def __repr__(self):
        return "CScriptWitness(%s)" % \
               (",".join([bytes_to_hex_str(x) for x in self.stack]))

    def is_null(self):
        if self.stack:
            return False
        return True


class CTxInWitness():
    def __init__(self):
        self.scriptWitness = CScriptWitness()

    def deserialize(self, f):
        self.scriptWitness.stack = deser_string_vector(f)

    def serialize(self):
        return ser_string_vector(self.scriptWitness.stack)

    def __repr__(self):
        return repr(self.scriptWitness)

    def is_null(self):
        return self.scriptWitness.is_null()


class CTxWitness():
    def __init__(self):
        self.vtxinwit = []

    def deserialize(self, f):
        for i in range(len(self.vtxinwit)):
            self.vtxinwit[i].deserialize(f)

    def serialize(self):
        r = b""
        # This is different than the usual vector serialization --
        # we omit the length of the vector, which is required to be
        # the same length as the transaction's vin vector.
        for x in self.vtxinwit:
            r += x.serialize()
        return r

    def __repr__(self):
        return "CTxWitness(%s)" % \
               (';'.join([repr(x) for x in self.vtxinwit]))

    def is_null(self):
        for x in self.vtxinwit:
            if not x.is_null():
                return False
        return True


class CTransaction():
    def __init__(self, tx=None):
        if tx is None:
            self.nVersion = 1
            self.vin = []
            self.vout = []
            self.wit = CTxWitness()
            self.nLockTime = 0
            self.sha256 = None
            self.hash = None
        else:
            self.nVersion = tx.nVersion
            self.vin = copy.deepcopy(tx.vin)
            self.vout = copy.deepcopy(tx.vout)
            self.nLockTime = tx.nLockTime
            self.sha256 = tx.sha256
            self.hash = tx.hash
            self.wit = copy.deepcopy(tx.wit)

    def set_type(self, tx_type):
        self.nVersion = (self.nVersion & 0x0000FFFF) | (tx_type.value << 16)

    def get_type(self):
        return TxType(self.nVersion >> 16)

    def is_finalizer_commit(self):
        name = self.get_type()
        if (name == TxType.VOTE or
            name == TxType.ADMIN or
            name == TxType.DEPOSIT or
            name == TxType.LOGOUT or
            name == TxType.SLASH or
            name == TxType.WITHDRAW):
            return True

        if (name == TxType.COINBASE or
            name == TxType.REGULAR):
            return False

        assert False, ('unknown type: %s' % name)

    def deserialize(self, f):
        self.nVersion = struct.unpack("<i", f.read(4))[0]
        self.vin = deser_vector(f, CTxIn)
        flags = 0
        if len(self.vin) == 0:
            flags = struct.unpack("<B", f.read(1))[0]
            # Not sure why flags can't be zero, but this
            # matches the implementation in unit-e
            if (flags != 0):
                self.vin = deser_vector(f, CTxIn)
                self.vout = deser_vector(f, CTxOut)
        else:
            self.vout = deser_vector(f, CTxOut)
        if flags != 0:
            self.wit.vtxinwit = [CTxInWitness() for i in range(len(self.vin))]
            self.wit.deserialize(f)
        self.nLockTime = struct.unpack("<I", f.read(4))[0]
        self.sha256 = None
        self.hash = None

    def serialize_without_witness(self):
        r = b""
        r += struct.pack("<i", self.nVersion)
        r += ser_vector(self.vin)
        r += ser_vector(self.vout)
        r += struct.pack("<I", self.nLockTime)
        return r

    # Only serialize with witness when explicitly called for
    def serialize_with_witness(self):
        flags = 0
        if not self.wit.is_null():
            flags |= 1
        r = b""
        r += struct.pack("<i", self.nVersion)
        if flags:
            dummy = []
            r += ser_vector(dummy)
            r += struct.pack("<B", flags)
        r += ser_vector(self.vin)
        r += ser_vector(self.vout)
        if flags & 1:
            if (len(self.wit.vtxinwit) != len(self.vin)):
                # vtxinwit must have the same length as vin
                self.wit.vtxinwit = self.wit.vtxinwit[:len(self.vin)]
                for i in range(len(self.wit.vtxinwit), len(self.vin)):
                    self.wit.vtxinwit.append(CTxInWitness())
            r += self.wit.serialize()
        r += struct.pack("<I", self.nLockTime)
        return r

    # Regular serialization is with witness -- must explicitly
    # call serialize_without_witness to exclude witness data.
    def serialize(self):
        return self.serialize_with_witness()

    # Recalculate the txid (transaction hash without witness)
    def rehash(self):
        self.sha256 = None
        self.calc_sha256()
        return self.hash

    # We will only cache the serialization without witness in
    # self.sha256 and self.hash -- those are expected to be the txid.
    def calc_sha256(self, with_witness=False):
        if with_witness:
            # Don't cache the result, just return it
            return uint256_from_str(hash256(self.serialize_with_witness()))

        if self.sha256 is None:
            self.sha256 = uint256_from_str(hash256(self.serialize_without_witness()))
        self.hash = encode(hash256(self.serialize_without_witness())[::-1], 'hex_codec').decode('ascii')

    def is_valid(self):
        self.calc_sha256()
        for tout in self.vout:
            if tout.nValue < 0 or tout.nValue > 21000000 * UNIT:
                return False
        return True

    def is_coin_base(self):
        return TxType(self.nVersion >> 16) == TxType.COINBASE

    def __repr__(self):
        return "CTransaction(nVersion=%i vin=%s vout=%s wit=%s nLockTime=%i)" \
            % (self.nVersion, repr(self.vin), repr(self.vout), repr(self.wit), self.nLockTime)


class CBlockHeader():
    def __init__(self, header=None):
        if header is None:
            self.set_null()
        else:
            self.nVersion = header.nVersion
            self.hashPrevBlock = header.hashPrevBlock
            self.hashMerkleRoot = header.hashMerkleRoot
            self.hash_witness_merkle_root = header.hash_witness_merkle_root
            self.hash_finalizer_commits_merkle_root = header.hash_finalizer_commits_merkle_root
            self.nTime = header.nTime
            self.nBits = header.nBits
            self.sha256 = header.sha256
            self.hash = header.hash
            self.calc_sha256()

    def set_null(self):
        self.nVersion = 1
        self.hashPrevBlock = 0
        self.hashMerkleRoot = 0
        self.hash_witness_merkle_root = 0
        self.hash_finalizer_commits_merkle_root = 0
        self.nTime = 0
        self.nBits = 0
        self.sha256 = None
        self.hash = None

    def deserialize(self, f):
        self.nVersion = struct.unpack("<i", f.read(4))[0]
        self.hashPrevBlock = deser_uint256(f)
        self.hashMerkleRoot = deser_uint256(f)
        self.hash_witness_merkle_root = deser_uint256(f)
        self.hash_finalizer_commits_merkle_root = deser_uint256(f)
        self.nTime = struct.unpack("<I", f.read(4))[0]
        self.nBits = struct.unpack("<I", f.read(4))[0]
        self.sha256 = None
        self.hash = None

    def serialize(self):
        r = b""
        r += struct.pack("<i", self.nVersion)
        r += ser_uint256(self.hashPrevBlock)
        r += ser_uint256(self.hashMerkleRoot)
        r += ser_uint256(self.hash_witness_merkle_root)
        r += ser_uint256(self.hash_finalizer_commits_merkle_root)
        r += struct.pack("<I", self.nTime)
        r += struct.pack("<I", self.nBits)
        return r

    def calc_sha256(self):
        if self.sha256 is None:
            r = b""
            r += struct.pack("<i", self.nVersion)
            r += ser_uint256(self.hashPrevBlock)
            r += ser_uint256(self.hashMerkleRoot)
            r += ser_uint256(self.hash_witness_merkle_root)
            r += ser_uint256(self.hash_finalizer_commits_merkle_root)
            r += struct.pack("<I", self.nTime)
            r += struct.pack("<I", self.nBits)
            self.sha256 = uint256_from_str(hash256(r))
            self.hash = encode(hash256(r)[::-1], 'hex_codec').decode('ascii')

    def rehash(self):
        self.sha256 = None
        self.calc_sha256()
        return self.sha256

    def __repr__(self):
        return ("CBlockHeader(nVersion=%i "
                "hashPrevBlock=%064x "
                "hashMerkleRoot=%064x "
                "hash_witness_merkle_root=%064x "
                "hash_finalizer_commits_merkle_root=%064x "
                "nTime=%s "
                "nBits=%08x)") \
            % (self.nVersion, self.hashPrevBlock, self.hashMerkleRoot, self.hash_witness_merkle_root,
               self.hash_finalizer_commits_merkle_root, time.ctime(self.nTime), self.nBits)


class CBlock(CBlockHeader):
    def __init__(self, header=None):
        super(CBlock, self).__init__(header)
        self.vtx = []

    def deserialize(self, f):
        super(CBlock, self).deserialize(f)
        self.vtx = deser_vector(f, CTransaction)

    def serialize(self, with_witness=False):
        r = b""
        r += super(CBlock, self).serialize()
        if with_witness:
            r += ser_vector(self.vtx, "serialize_with_witness")
        else:
            r += ser_vector(self.vtx, "serialize_without_witness")
        # UNIT-E: serialize an empty block signature on top of the block
        # this is just an interim solution
        r += ser_vector([])
        return r

    # Calculate the merkle root given a vector of transaction hashes
    @classmethod
    def get_merkle_root(cls, hashes):
        if len(hashes) == 0:
            return 0
        while len(hashes) > 1:
            newhashes = []
            for i in range(0, len(hashes), 2):
                i2 = min(i+1, len(hashes)-1)
                newhashes.append(hash256(hashes[i] + hashes[i2]))
            hashes = newhashes
        return uint256_from_str(hashes[0])

    def calc_merkle_root(self):
        hashes = []
        for tx in self.vtx:
            tx.calc_sha256()
            hashes.append(ser_uint256(tx.sha256))
        return self.get_merkle_root(hashes)

    def calc_witness_merkle_root(self):
        hashes = []
        for tx in self.vtx:
            # Calculate the hashes with witness data
            hashes.append(ser_uint256(tx.calc_sha256(True)))
        return self.get_merkle_root(hashes)

    def calc_finalizer_commits_merkle_root(self):
        hashes = []
        for tx in self.vtx:
            if tx.is_finalizer_commit():
                tx.calc_sha256()
                hashes.append(ser_uint256(tx.sha256))
        return self.get_merkle_root(hashes)

    def compute_merkle_trees(self):
        self.hashMerkleRoot = self.calc_merkle_root()
        self.hash_witness_merkle_root = self.calc_witness_merkle_root()
        self.hash_finalizer_commits_merkle_root = self.calc_finalizer_commits_merkle_root()

    def is_valid(self):
        self.calc_sha256()
        target = uint256_from_compact(self.nBits)
        if self.sha256 > target:
            return False
        for tx in self.vtx:
            if not tx.is_valid():
                return False
        if self.calc_merkle_root() != self.hashMerkleRoot:
            return False
        if self.calc_witness_merkle_root() != self.hash_witness_merkle_root:
            return False
        if self.calc_finalizer_commits_merkle_root() != self.hash_finalizer_commits_merkle_root:
            return False
        return True

    def solve(self):
        self.rehash()

    def ensure_ltor(self):
        if len(self.vtx) <= 1:
            return
        for tx in self.vtx:
            tx.rehash()
        self.vtx = [self.vtx[0]] + sorted(self.vtx[1:], key=lambda _tx: _tx.hash)

    def __repr__(self):
        return ("CBlock(nVersion=%i "
                "hashPrevBlock=%064x "
                "hashMerkleRoot=%064x "
                "hash_witness_merkle_root=%064x "
                "hash_finalizer_commits_merkle_root=%064x "
                "nTime=%s "
                "nBits=%08x "
                "vtx=%s)") \
            % (self.nVersion, self.hashPrevBlock, self.hashMerkleRoot, self.hash_witness_merkle_root,
               self.hash_finalizer_commits_merkle_root, time.ctime(self.nTime), self.nBits, repr(self.vtx))


class PrefilledTransaction():
    def __init__(self, index=0, tx = None):
        self.index = index
        self.tx = tx

    def deserialize(self, f):
        self.index = deser_compact_size(f)
        self.tx = CTransaction()
        self.tx.deserialize(f)

    def serialize(self, with_witness=True):
        r = b""
        r += ser_compact_size(self.index)
        if with_witness:
            r += self.tx.serialize_with_witness()
        else:
            r += self.tx.serialize_without_witness()
        return r

    def serialize_without_witness(self):
        return self.serialize(with_witness=False)

    def serialize_with_witness(self):
        return self.serialize(with_witness=True)

    def __repr__(self):
        return "PrefilledTransaction(index=%d, tx=%s)" % (self.index, repr(self.tx))

# This is what we send on the wire, in a cmpctblock message.
class P2PHeaderAndShortIDs():
    def __init__(self):
        self.header = CBlockHeader()
        self.nonce = 0
        self.shortids_length = 0
        self.shortids = []
        self.prefilled_txn_length = 0
        self.prefilled_txn = []

    def deserialize(self, f):
        self.header.deserialize(f)
        self.nonce = struct.unpack("<Q", f.read(8))[0]
        self.shortids_length = deser_compact_size(f)
        for i in range(self.shortids_length):
            # shortids are defined to be 6 bytes in the spec, so append
            # two zero bytes and read it in as an 8-byte number
            self.shortids.append(struct.unpack("<Q", f.read(6) + b'\x00\x00')[0])
        self.prefilled_txn = deser_vector(f, PrefilledTransaction)
        self.prefilled_txn_length = len(self.prefilled_txn)

    # When using version 2 compact blocks, we must serialize with_witness.
    def serialize(self, with_witness=False):
        r = b""
        r += self.header.serialize()
        r += struct.pack("<Q", self.nonce)
        r += ser_compact_size(self.shortids_length)
        for x in self.shortids:
            # We only want the first 6 bytes
            r += struct.pack("<Q", x)[0:6]
        if with_witness:
            r += ser_vector(self.prefilled_txn, "serialize_with_witness")
        else:
            r += ser_vector(self.prefilled_txn, "serialize_without_witness")
        return r

    def __repr__(self):
        return "P2PHeaderAndShortIDs(header=%s, nonce=%d, shortids_length=%d, shortids=%s, prefilled_txn_length=%d, prefilledtxn=%s" % (repr(self.header), self.nonce, self.shortids_length, repr(self.shortids), self.prefilled_txn_length, repr(self.prefilled_txn))

# P2P version of the above that will use witness serialization (for compact
# block version 2)
class P2PHeaderAndShortWitnessIDs(P2PHeaderAndShortIDs):
    def serialize(self):
        return super(P2PHeaderAndShortWitnessIDs, self).serialize(with_witness=True)

# Calculate the BIP 152-compact blocks shortid for a given transaction hash
def calculate_shortid(k0, k1, tx_hash):
    expected_shortid = siphash256(k0, k1, tx_hash)
    expected_shortid &= 0x0000ffffffffffff
    return expected_shortid

# This version gets rid of the array lengths, and reinterprets the differential
# encoding into indices that can be used for lookup.
class HeaderAndShortIDs():
    def __init__(self, p2pheaders_and_shortids = None):
        self.header = CBlockHeader()
        self.nonce = 0
        self.shortids = []
        self.prefilled_txn = []
        self.use_witness = False

        if p2pheaders_and_shortids != None:
            self.header = p2pheaders_and_shortids.header
            self.nonce = p2pheaders_and_shortids.nonce
            self.shortids = p2pheaders_and_shortids.shortids
            last_index = -1
            for x in p2pheaders_and_shortids.prefilled_txn:
                self.prefilled_txn.append(PrefilledTransaction(x.index + last_index + 1, x.tx))
                last_index = self.prefilled_txn[-1].index

    def to_p2p(self):
        if self.use_witness:
            ret = P2PHeaderAndShortWitnessIDs()
        else:
            ret = P2PHeaderAndShortIDs()
        ret.header = self.header
        ret.nonce = self.nonce
        ret.shortids_length = len(self.shortids)
        ret.shortids = self.shortids
        ret.prefilled_txn_length = len(self.prefilled_txn)
        ret.prefilled_txn = []
        last_index = -1
        for x in self.prefilled_txn:
            ret.prefilled_txn.append(PrefilledTransaction(x.index - last_index - 1, x.tx))
            last_index = x.index
        return ret

    def get_siphash_keys(self):
        header_nonce = self.header.serialize()
        header_nonce += struct.pack("<Q", self.nonce)
        hash_header_nonce_as_str = sha256(header_nonce)
        key0 = struct.unpack("<Q", hash_header_nonce_as_str[0:8])[0]
        key1 = struct.unpack("<Q", hash_header_nonce_as_str[8:16])[0]
        return [ key0, key1 ]

    # Version 2 compact blocks use wtxid in shortids (rather than txid)
    def initialize_from_block(self, block, prefill = [], add_genesis=True, nonce=0, use_witness = True):
        self.header = CBlockHeader(block)
        self.nonce = nonce
        if add_genesis:
            if block.vtx[0] not in prefill:
                prefill = [block.vtx[0]] + prefill

        self.prefilled_txn = [ PrefilledTransaction(block.vtx.index(tx), tx) for tx in prefill ]
        self.prefilled_txn.sort(key=lambda tx: tx.index) # the prefilled transactions can be out of order
        self.shortids = []
        self.use_witness = use_witness
        [k0, k1] = self.get_siphash_keys()

        for tx in block.vtx:
            if tx not in prefill:
                tx_hash = tx.sha256
                if use_witness:
                    tx_hash = tx.calc_sha256(with_witness=True)
                self.shortids.append(calculate_shortid(k0, k1, tx_hash))

    def __repr__(self):
        return "HeaderAndShortIDs(header=%s, nonce=%d, shortids=%s, prefilledtxn=%s" % (repr(self.header), self.nonce, repr(self.shortids), repr(self.prefilled_txn))


class BlockTransactionsRequest():

    def __init__(self, blockhash=0, indexes = None):
        self.blockhash = blockhash
        self.indexes = indexes if indexes != None else []

    def deserialize(self, f):
        self.blockhash = deser_uint256(f)
        indexes_length = deser_compact_size(f)
        for i in range(indexes_length):
            self.indexes.append(deser_compact_size(f))

    def serialize(self):
        r = b""
        r += ser_uint256(self.blockhash)
        r += ser_compact_size(len(self.indexes))
        for x in self.indexes:
            r += ser_compact_size(x)
        return r

    # helper to set the differentially encoded indexes from absolute ones
    def from_absolute(self, absolute_indexes):
        self.indexes = []
        last_index = -1
        for x in absolute_indexes:
            self.indexes.append(x-last_index-1)
            last_index = x

    def to_absolute(self):
        absolute_indexes = []
        last_index = -1
        for x in self.indexes:
            absolute_indexes.append(x+last_index+1)
            last_index = absolute_indexes[-1]
        return absolute_indexes

    def __repr__(self):
        return "BlockTransactionsRequest(hash=%064x indexes=%s)" % (self.blockhash, repr(self.indexes))


class BlockTransactions():

    def __init__(self, blockhash=0, transactions = None):
        self.blockhash = blockhash
        self.transactions = transactions if transactions != None else []

    def deserialize(self, f):
        self.blockhash = deser_uint256(f)
        self.transactions = deser_vector(f, CTransaction)

    def serialize(self, with_witness=True):
        r = b""
        r += ser_uint256(self.blockhash)
        if with_witness:
            r += ser_vector(self.transactions, "serialize_with_witness")
        else:
            r += ser_vector(self.transactions, "serialize_without_witness")
        return r

    def __repr__(self):
        return "BlockTransactions(hash=%064x transactions=%s)" % (self.blockhash, repr(self.transactions))

class CPartialMerkleTree():
    def __init__(self):
        self.nTransactions = 0
        self.vHash = []
        self.vBits = []
        self.fBad = False

    def deserialize(self, f):
        self.nTransactions = struct.unpack("<i", f.read(4))[0]
        self.vHash = deser_uint256_vector(f)
        vBytes = deser_string(f)
        self.vBits = []
        for i in range(len(vBytes) * 8):
            self.vBits.append(vBytes[i//8] & (1 << (i % 8)) != 0)

    def serialize(self):
        r = b""
        r += struct.pack("<i", self.nTransactions)
        r += ser_uint256_vector(self.vHash)
        vBytesArray = bytearray([0x00] * ((len(self.vBits) + 7)//8))
        for i in range(len(self.vBits)):
            vBytesArray[i // 8] |= self.vBits[i] << (i % 8)
        r += ser_string(bytes(vBytesArray))
        return r

    def __repr__(self):
        return "CPartialMerkleTree(nTransactions=%d, vHash=%s, vBits=%s)" % (self.nTransactions, repr(self.vHash), repr(self.vBits))

class CMerkleBlock():
    def __init__(self):
        self.header = CBlockHeader()
        self.txn = CPartialMerkleTree()

    def deserialize(self, f):
        self.header.deserialize(f)
        self.txn.deserialize(f)

    def serialize(self):
        r = b""
        r += self.header.serialize()
        r += self.txn.serialize()
        return r

    def __repr__(self):
        return "CMerkleBlock(header=%s, txn=%s)" % (repr(self.header), repr(self.txn))


# Objects that correspond to messages on the wire
class msg_version():
    command = b"version"

    def __init__(self):
        self.nVersion = MY_VERSION
        self.nServices = NODE_NETWORK | NODE_WITNESS
        self.nTime = int(time.time())
        self.addrTo = CAddress()
        self.addrFrom = CAddress()
        self.nNonce = random.getrandbits(64)
        self.strSubVer = MY_SUBVERSION
        self.nStartingHeight = -1
        self.nRelay = MY_RELAY

    def deserialize(self, f):
        self.nVersion = struct.unpack("<i", f.read(4))[0]
        if self.nVersion == 10300:
            self.nVersion = 300
        self.nServices = struct.unpack("<Q", f.read(8))[0]
        self.nTime = struct.unpack("<q", f.read(8))[0]
        self.addrTo = CAddress()
        self.addrTo.deserialize(f, False)

        if self.nVersion >= 106:
            self.addrFrom = CAddress()
            self.addrFrom.deserialize(f, False)
            self.nNonce = struct.unpack("<Q", f.read(8))[0]
            self.strSubVer = deser_string(f)
        else:
            self.addrFrom = None
            self.nNonce = None
            self.strSubVer = None
            self.nStartingHeight = None

        if self.nVersion >= 209:
            self.nStartingHeight = struct.unpack("<i", f.read(4))[0]
        else:
            self.nStartingHeight = None

        if self.nVersion >= 70001:
            # Relay field is optional for version 70001 onwards
            try:
                self.nRelay = struct.unpack("<b", f.read(1))[0]
            except:
                self.nRelay = 0
        else:
            self.nRelay = 0

    def serialize(self):
        r = b""
        r += struct.pack("<i", self.nVersion)
        r += struct.pack("<Q", self.nServices)
        r += struct.pack("<q", self.nTime)
        r += self.addrTo.serialize(False)
        r += self.addrFrom.serialize(False)
        r += struct.pack("<Q", self.nNonce)
        r += ser_string(self.strSubVer)
        r += struct.pack("<i", self.nStartingHeight)
        r += struct.pack("<b", self.nRelay)
        return r

    def __repr__(self):
        return 'msg_version(nVersion=%i nServices=%i nTime=%s addrTo=%s addrFrom=%s nNonce=0x%016X strSubVer=%s nStartingHeight=%i nRelay=%i)' \
            % (self.nVersion, self.nServices, time.ctime(self.nTime),
               repr(self.addrTo), repr(self.addrFrom), self.nNonce,
               self.strSubVer, self.nStartingHeight, self.nRelay)


class msg_verack():
    command = b"verack"

    def __init__(self):
        pass

    def deserialize(self, f):
        pass

    def serialize(self):
        return b""

    def __repr__(self):
        return "msg_verack()"


class msg_addr():
    command = b"addr"

    def __init__(self):
        self.addrs = []

    def deserialize(self, f):
        self.addrs = deser_vector(f, CAddress)

    def serialize(self):
        return ser_vector(self.addrs)

    def __repr__(self):
        return "msg_addr(addrs=%s)" % (repr(self.addrs))


class msg_inv():
    command = b"inv"

    def __init__(self, inv=None):
        if inv is None:
            self.inv = []
        else:
            self.inv = inv

    def deserialize(self, f):
        self.inv = deser_vector(f, CInv)

    def serialize(self):
        return ser_vector(self.inv)

    def __repr__(self):
        return "msg_inv(inv=%s)" % (repr(self.inv))


class msg_getdata():
    command = b"getdata"

    def __init__(self, inv=None):
        self.inv = inv if inv != None else []

    def deserialize(self, f):
        self.inv = deser_vector(f, CInv)

    def serialize(self):
        return ser_vector(self.inv)

    def __repr__(self):
        return "msg_getdata(inv=%s)" % (repr(self.inv))


class msg_getblocks():
    command = b"getblocks"

    def __init__(self):
        self.locator = CBlockLocator()
        self.hashstop = 0

    def deserialize(self, f):
        self.locator = CBlockLocator()
        self.locator.deserialize(f)
        self.hashstop = deser_uint256(f)

    def serialize(self):
        r = b""
        r += self.locator.serialize()
        r += ser_uint256(self.hashstop)
        return r

    def __repr__(self):
        return "msg_getblocks(locator=%s hashstop=%064x)" \
            % (repr(self.locator), self.hashstop)


class msg_tx():
    command = b"tx"

    def __init__(self, tx=CTransaction()):
        self.tx = tx

    def deserialize(self, f):
        self.tx.deserialize(f)

    def serialize(self):
        return self.tx.serialize_without_witness()

    def __repr__(self):
        return "msg_tx(tx=%s)" % (repr(self.tx))

class msg_witness_tx(msg_tx):

    def serialize(self):
        return self.tx.serialize_with_witness()


class msg_block():
    command = b"block"

    def __init__(self, block=None):
        if block is None:
            self.block = CBlock()
        else:
            self.block = block

    def deserialize(self, f):
        self.block.deserialize(f)

    def serialize(self):
        return self.block.serialize(with_witness=True)

    def __repr__(self):
        return "msg_block(block=%s)" % (repr(self.block))

# for cases where a user needs tighter control over what is sent over the wire
# note that the user must supply the name of the command, and the data
class msg_generic():
    def __init__(self, command, data=None):
        self.command = command
        self.data = data

    def serialize(self):
        return self.data

    def __repr__(self):
        return "msg_generic()"

class msg_getaddr():
    command = b"getaddr"

    def __init__(self):
        pass

    def deserialize(self, f):
        pass

    def serialize(self):
        return b""

    def __repr__(self):
        return "msg_getaddr()"


class msg_ping():
    command = b"ping"

    def __init__(self, nonce=0):
        self.nonce = nonce

    def deserialize(self, f):
        self.nonce = struct.unpack("<Q", f.read(8))[0]

    def serialize(self):
        r = b""
        r += struct.pack("<Q", self.nonce)
        return r

    def __repr__(self):
        return "msg_ping(nonce=%08x)" % self.nonce


class msg_pong():
    command = b"pong"

    def __init__(self, nonce=0):
        self.nonce = nonce

    def deserialize(self, f):
        self.nonce = struct.unpack("<Q", f.read(8))[0]

    def serialize(self):
        r = b""
        r += struct.pack("<Q", self.nonce)
        return r

    def __repr__(self):
        return "msg_pong(nonce=%08x)" % self.nonce


class msg_mempool():
    command = b"mempool"

    def __init__(self):
        pass

    def deserialize(self, f):
        pass

    def serialize(self):
        return b""

    def __repr__(self):
        return "msg_mempool()"

class msg_sendheaders():
    command = b"sendheaders"

    def __init__(self):
        pass

    def deserialize(self, f):
        pass

    def serialize(self):
        return b""

    def __repr__(self):
        return "msg_sendheaders()"


# getheaders message has
# number of entries
# vector of hashes
# hash_stop (hash of last desired block header, 0 to get as many as possible)
class msg_getheaders():
    command = b"getheaders"

    def __init__(self):
        self.locator = CBlockLocator()
        self.hashstop = 0

    def deserialize(self, f):
        self.locator = CBlockLocator()
        self.locator.deserialize(f)
        self.hashstop = deser_uint256(f)

    def serialize(self):
        r = b""
        r += self.locator.serialize()
        r += ser_uint256(self.hashstop)
        return r

    def __repr__(self):
        return "msg_getheaders(locator=%s, stop=%064x)" \
            % (repr(self.locator), self.hashstop)


# headers message has
# <count> <vector of block headers>
class msg_headers():
    command = b"headers"

    def __init__(self, headers=None):
        self.headers = headers if headers is not None else []

    def deserialize(self, f):
        blocks = deser_vector(f, CBlockHeader)
        for x in blocks:
            self.headers.append(x)

    def serialize(self):
        headers_to_send = []
        for header in self.headers:
            headers_to_send.append(CBlockHeader(header))
        return ser_vector(headers_to_send)

    def __repr__(self):
        return "msg_headers(headers=%s)" % repr(self.headers)


class msg_reject():
    command = b"reject"
    REJECT_MALFORMED = 1

    def __init__(self):
        self.message = b""
        self.code = 0
        self.reason = b""
        self.data = 0

    def deserialize(self, f):
        self.message = deser_string(f)
        self.code = struct.unpack("<B", f.read(1))[0]
        self.reason = deser_string(f)
        if (self.code != self.REJECT_MALFORMED and
                (self.message == b"block" or self.message == b"tx")):
            self.data = deser_uint256(f)

    def serialize(self):
        r = ser_string(self.message)
        r += struct.pack("<B", self.code)
        r += ser_string(self.reason)
        if (self.code != self.REJECT_MALFORMED and
                (self.message == b"block" or self.message == b"tx")):
            r += ser_uint256(self.data)
        return r

    def __repr__(self):
        return "msg_reject: %s %d %s [%064x]" \
            % (self.message, self.code, self.reason, self.data)

class msg_feefilter():
    command = b"feefilter"

    def __init__(self, feerate=0):
        self.feerate = feerate

    def deserialize(self, f):
        self.feerate = struct.unpack("<Q", f.read(8))[0]

    def serialize(self):
        r = b""
        r += struct.pack("<Q", self.feerate)
        return r

    def __repr__(self):
        return "msg_feefilter(feerate=%08x)" % self.feerate

class msg_sendcmpct():
    command = b"sendcmpct"

    def __init__(self):
        self.announce = False
        self.version = 1

    def deserialize(self, f):
        self.announce = struct.unpack("<?", f.read(1))[0]
        self.version = struct.unpack("<Q", f.read(8))[0]

    def serialize(self):
        r = b""
        r += struct.pack("<?", self.announce)
        r += struct.pack("<Q", self.version)
        return r

    def __repr__(self):
        return "msg_sendcmpct(announce=%s, version=%lu)" % (self.announce, self.version)

class msg_cmpctblock():
    command = b"cmpctblock"

    def __init__(self, header_and_shortids = None):
        self.header_and_shortids = header_and_shortids

    def deserialize(self, f):
        self.header_and_shortids = P2PHeaderAndShortIDs()
        self.header_and_shortids.deserialize(f)

    def serialize(self):
        r = b""
        r += self.header_and_shortids.serialize()
        return r

    def __repr__(self):
        return "msg_cmpctblock(HeaderAndShortIDs=%s)" % repr(self.header_and_shortids)

class msg_getblocktxn():
    command = b"getblocktxn"

    def __init__(self):
        self.block_txn_request = None

    def deserialize(self, f):
        self.block_txn_request = BlockTransactionsRequest()
        self.block_txn_request.deserialize(f)

    def serialize(self):
        r = b""
        r += self.block_txn_request.serialize()
        return r

    def __repr__(self):
        return "msg_getblocktxn(block_txn_request=%s)" % (repr(self.block_txn_request))

class msg_blocktxn():
    command = b"blocktxn"

    def __init__(self):
        self.block_transactions = BlockTransactions()

    def deserialize(self, f):
        self.block_transactions.deserialize(f)

    def serialize(self):
        r = b""
        r += self.block_transactions.serialize(with_witness=False)
        return r

    def __repr__(self):
        return "msg_blocktxn(block_transactions=%s)" % (repr(self.block_transactions))

class msg_witness_blocktxn(msg_blocktxn):
    def serialize(self):
        r = b""
        r += self.block_transactions.serialize(with_witness=True)
        return r

class msg_getsnaphead:
    command = b"getsnaphead"

    def serialize(self):
        r = b""
        return r

    def deserialize(self, f): pass

    def __repr__(self):
        return "msg_getsnaphead"


class msg_snaphead:
    command = b"snaphead"

    def __init__(self, snapshot_header=None):
        self.snapshot_header = SnapshotHeader() if snapshot_header is None else snapshot_header

    def serialize(self):
        return self.snapshot_header.serialize()

    def deserialize(self, f):
        self.snapshot_header.deserialize(f)

    def __repr__(self):
        return "msg_snaphead(%s)" % (repr(self.snapshot_header))


class SnapshotHeader:
    def __init__(self, snapshot_hash=0, block_hash=0, stake_modifier=0, chain_work=0, total_utxo_subsets=0):
        self.snapshot_hash = snapshot_hash
        self.block_hash = block_hash
        self.stake_modifier = stake_modifier
        self.chain_work = chain_work
        self.total_utxo_subsets = total_utxo_subsets

    def deserialize(self, f):
        self.snapshot_hash = deser_uint256(f)
        self.block_hash = deser_uint256(f)
        self.stake_modifier = deser_uint256(f)
        self.chain_work = deser_uint256(f)
        self.total_utxo_subsets = struct.unpack('<Q', f.read(8))[0]

    def serialize(self):
        r = b""
        r += ser_uint256(self.snapshot_hash)
        r += ser_uint256(self.block_hash)
        r += ser_uint256(self.stake_modifier)
        r += ser_uint256(self.chain_work)
        r += struct.pack('<Q', self.total_utxo_subsets)
        return r

    def __repr__(self):
        return "SnapshotHeader(snapshot_hash=%064x block_hash=%064x stake_modifier=%064x chain_work=%064x total_utxo_subsets=%i)" \
                % (self.snapshot_hash, self.block_hash, self.stake_modifier, self.chain_work, self.total_utxo_subsets)


class msg_getsnapshot:
    command = b"getsnapshot"

    def __init__(self, getsnapshot=None):
        self.getsnapshot = GetSnapshot() if getsnapshot is None else getsnapshot

    def serialize(self):
        return self.getsnapshot.serialize()

    def deserialize(self, f):
        self.getsnapshot.deserialize(f)

    def __repr__(self):
        return "msg_getsnapshot(%s)" % (repr(self.getsnapshot))


class GetSnapshot:
    def __init__(self, snapshot_hash=0, index=0, count=0):
        self.snapshot_hash = snapshot_hash
        self.utxo_subset_index = index
        self.utxo_subset_count = count

    def deserialize(self, f):
        self.snapshot_hash = deser_uint256(f)
        self.utxo_subset_index = struct.unpack('<Q', f.read(8))[0]
        self.utxo_subset_count = struct.unpack('<H', f.read(2))[0]

    def serialize(self):
        r = b""
        r += ser_uint256(self.snapshot_hash)
        r += struct.pack('<Q', self.utxo_subset_index)
        r += struct.pack('<H', self.utxo_subset_count)
        return r

    def __repr__(self):
        return "GetSnapshot(snapshot_hash=%064x utxo_subset_index=%i utxo_subset_count=%i)" \
                % (self.snapshot_hash, self.utxo_subset_index, self.utxo_subset_count)


class msg_snapshot:
    command = b"snapshot"

    def __init__(self, snapshot=None):
        self.snapshot = Snapshot() if snapshot is None else snapshot

    def serialize(self):
        return self.snapshot.serialize()

    def deserialize(self, f):
        self.snapshot.deserialize(f)

    def __repr__(self):
        return "msg_snapshot(%s)" % (repr(self.snapshot))


class Snapshot:
    def __init__(self, snapshot_hash=0, utxo_subset_index=0, utxo_subsets=[]):
        self.snapshot_hash = snapshot_hash
        self.utxo_subset_index = utxo_subset_index
        self.utxo_subsets = utxo_subsets

    def deserialize(self, f):
        self.snapshot_hash = deser_uint256(f)
        self.utxo_subset_index = struct.unpack('<Q', f.read(8))[0]
        self.utxo_subsets = deser_vector(f, UTXOSubset)

    def serialize(self):
        r = b""
        r += ser_uint256(self.snapshot_hash)
        r += struct.pack('<Q', self.utxo_subset_index)
        r += ser_vector(self.utxo_subsets)
        return r

    def __repr__(self):
        return "Snapshot(snapshot_hash=%064x utxo_subset_index=%i, utxo_subsets=%s)" \
                % (self.snapshot_hash, self.utxo_subset_index, repr(self.utxo_subsets))


class UTXOSubset:
    def __init__(self):
        self.tx_id = 0
        self.height = 0
        self.tx_type = TxType.REGULAR
        self.outputs = dict()

    def deserialize(self, f):
        self.tx_id = deser_uint256(f)
        self.height = struct.unpack('<I', f.read(4))[0]
        self.tx_type = TxType(struct.unpack('<B', f.read(1))[0])
        self.outputs = deser_uint32_map(f, CTxOut)

    def serialize(self):
        r = b""
        r += ser_uint256(self.tx_id)
        r += struct.pack('<I', self.height)
        r += struct.pack('<B', self.tx_type.value)
        r += ser_uint32_map(self.outputs)
        return r

    def __repr__(self):
        return "UTXOSubset(tx_id=%064x height=%i, tx_type=%s outputs=%s)" \
                % (self.tx_id, self.height, self.tx_type.name, repr(self.outputs))


class msg_notfound():
    command = b"notfound"

    def __init__(self, inv=None):
        self.inv = inv if inv != None else []

    def deserialize(self, f):
        self.inv = deser_vector(f, CInv)

    def serialize(self):
        return ser_vector(self.inv)

    def __repr__(self):
        return "msg_notfound(inv=%s)" % (repr(self.inv))


class CommitsLocator():
    def __init__(self, start=[], stop=0):
        self.start = start
        self.stop = stop

    def deserialize(self, f):
        self.start = deser_uint256_vector(f)
        self.stop = deser_uint256(f)

    def serialize(self):
        r = b""
        r += ser_uint256_vector(self.start)
        r += ser_uint256(self.stop)
        return r

    def __repr__(self):
        return "CommitsLocator(start=%s stop=%064x)" \
            % (repr(self.start), self.stop)


class msg_getcommits:
    command = b"getcommits"

    def __init__(self, locator=None):
        if locator is None:
            self.locator = CommitsLocator()
        else:
            self.locator = locator

    def deserialize(self, f):
        self.locator.deserialize(f)

    def serialize(self):
        r = b""
        r += self.locator.serialize()
        return r

    def __repr__(self):
        return "getcommits(%s)" % (repr(self.locator))

class HeaderAndCommits:
    def __init__(self, header=None):
        self.header = header if header is not None else CBlockHeader()
        self.commits = []

    def deserialize(self, f):
        self.header.deserialize(f)
        self.header.calc_sha256()
        self.commits = deser_vector(f, CTransaction)

    def serialize(self):
        r = b""
        r += self.header.serialize()
        r += ser_vector(self.commits, "serialize_without_witness")
        return r

class msg_commits:
    command = b"commits"

    def __init__(self, status=0):
        self.status = status
        self.data = []

    def __repr__(self):
        return "msg_commits(status={0}, length={1}, first={2})".format(
            self.status, len(self.data), self.data[0].header.hash if len(self.data) > 0 else "Nil")

    def deserialize(self, f):
        self.status = struct.unpack("<B", f.read(1))[0]
        self.data = deser_vector(f, HeaderAndCommits)

    def serialize(self):
        r = b""
        r += struct.pack("<B", self.status)
        r += ser_vector(self.data)
        return r


class GrapheneBlockRequest:
    def __init__(self, requested_block_hash=None, requester_mempool_count=0):
        self.requested_block_hash = requested_block_hash
        self.requester_mempool_count = requester_mempool_count

    def deserialize(self, f):
        self.requested_block_hash = deser_uint256(f)
        self.requester_mempool_count = deser_uint64(f)

    def serialize(self):
        r = b""
        r += ser_uint256(self.requested_block_hash)
        r += ser_uint64(self.requester_mempool_count)
        return r

    def __repr__(self):
        return "GrapheneBlockRequest(hash=%064x mempool=%d)" % (self.requested_block_hash, self.requester_mempool_count)


class msg_getgraphene:
    command = b'getgraphene'

    def __init__(self, request=None):
        if request is None:
            self.request = GrapheneBlockRequest()
        else:
            self.request = request

    def deserialize(self, f):
        self.request.deserialize(f)

    def serialize(self):
        r = b""
        r += self.request.serialize()
        return r

    def __repr__(self):
        return "msg_getgraphene(request=%s)" % (repr(self.request))


class CBloomFilterDummy:
    def __init__(self):
        self.vData = b"ffff"
        self.nHashFuncs = 1
        self.nTweak = 0
        self.nFlags = 0

    def deserialize(self, f):
        self.vData = deser_string(f)
        self.nHashFuncs = struct.unpack("<I", f.read(4))[0]
        self.nTweak = struct.unpack("<I", f.read(4))[0]
        self.nFlags = struct.unpack("<B", f.read(1))[0]

    def serialize(self):
        r = b""
        r += ser_string(self.vData)
        r += struct.pack("<I", self.nHashFuncs & 0xFFFFFFFF)
        r += struct.pack("<I", self.nTweak & 0xFFFFFFFF)
        r += struct.pack("<B", self.nFlags & 0xFF)

        return r

    def __repr__(self):
        return "CBloomFilterDummy"


class GrapheneIbltEntryDummy:
    def __init__(self):
        self.count = 0
        self.key_sum = 0
        self.key_check = 0

    def serialize(self):
        r = b""
        r += ser_compact_size(self.count)
        r += ser_uint64(self.key_sum)
        r += ser_uint32(self.key_check)

        return r

    def deserialize(self, f):
        self.count = deser_compact_size(f)
        self.key_sum = deser_uint64(f)
        self.key_check = deser_uint32(f)


# Can serialize/deserialize IBLT as is,
# but does not contain IBLT computation logic
class GrapheneIbltDummy:
    def __init__(self):
        self.hash_table = []
        self.num_hashes = 1

    def deserialize(self, f):
        self.hash_table = deser_vector(f, GrapheneIbltEntryDummy)
        self.num_hashes = struct.unpack("<B", f.read(1))[0]

    def serialize(self):
        r = b""
        r += ser_vector(self.hash_table)
        r += struct.pack("<B", self.num_hashes & 0xFF)
        return r

    def __repr__(self):
        return "GrapheneIbltDummy"


class GrapheneBlock:
    def __init__(self):
        self.header = CBlockHeader()
        self.nonce = 0
        self.bloom_filter = CBloomFilterDummy()
        self.iblt = GrapheneIbltDummy()
        self.prefilled_transactions = []

    def deserialize(self, f):
        self.header.deserialize(f)
        self.nonce = deser_uint64(f)
        self.bloom_filter.deserialize(f)
        self.iblt.deserialize(f)
        self.prefilled_transactions = deser_vector(f, CTransaction)

    def serialize(self):
        r = b""
        r += self.header.serialize()
        r += ser_uint64(self.nonce)
        r += self.bloom_filter.serialize()
        r += self.iblt.serialize()
        r += ser_vector(self.prefilled_transactions)

        return r

    def __repr__(self):
        return "GrapheneBlock(header=%s, nonce=%s, bloom_filter=%s, iblt=%s, prefilled_transactions=%s)" % \
               (repr(self.header), repr(self.nonce), repr(self.bloom_filter), repr(self.iblt), repr(self.prefilled_transactions))


class msg_graphenblock:
    command = b'graphenblock'

    def __init__(self, block=None):
        if block is None:
            self.block = GrapheneBlock()
        else:
            self.block = block

    def deserialize(self, f):
        self.block.deserialize(f)

    def serialize(self):
        r = b""
        r += self.block.serialize()
        return r

    def __repr__(self):
        return "msg_graphenblock(block=%s)" % repr(self.block)


class GrapheneTxRequest:
    def __init__(self):
        self.block_hash = None
        self.missing_tx_short_hashes = []

    def serialize(self):
        r = b""
        r += ser_uint256(self.block_hash)
        r += ser_compact_size(len(self.missing_tx_short_hashes))
        for hash in self.missing_tx_short_hashes:
            r += ser_uint64(hash)

        return r

    def deserialize(self, f):
        self.block_hash = deser_uint256(f)
        self.missing_tx_short_hashes.clear()
        for _ in range(deser_compact_size(f)):
            self.missing_tx_short_hashes.append(deser_uint64(f))

    def __repr__(self):
        return "GrapheneTxRequest(block_hash=%064x missing_tx_short_hashes=%s)" %\
               (self.block_hash, repr(self.missing_tx_short_hashes))


class msg_getgraphentx:
    command = b"getgraphentx"

    def __init__(self):
        self.request = GrapheneTxRequest()

    def serialize(self):
        r = "b"
        r += self.request.serialize()
        return r

    def deserialize(self, f):
        self.request.deserialize(f)

    def __repr__(self):
        return "msg_getgraphentx(request=%s)" % repr(self.request)


class GrapheneTx:
    def __init__(self, block_hash=None, txs=None):
        if block_hash is None:
            self.block_hash = None
        else:
            self.block_hash = block_hash

        if txs is None:
            self.txs = []
        else:
            self.txs = txs

    def deserialize(self, f):
        self.block_hash = deser_uint256(f)
        self.txs = deser_vector(f, CTransaction)

    def serialize(self):
        r = b""
        r += ser_uint256(self.block_hash)
        r += ser_vector(self.txs, "serialize_with_witness")
        return r

    def __repr__(self):
        return "GrapheneTx(hash=%064x transactions=%s)" % (self.block_hash, repr(self.txs))


class msg_graphenetx:
    command = b"graphenetx"

    def __init__(self, graphene_tx=None):
        if graphene_tx is None:
            self.graphene_tx = GrapheneTx()
        else:
            self.graphene_tx = graphene_tx

    def deserialize(self, f):
        self.graphene_tx.deserialize(f)

    def serialize(self):
        r = b""
        r += self.graphene_tx.serialize()
        return r

    def __repr__(self):
        return "msg_graphenetx(graphene_tx=%s)" % repr(self.graphene_tx)
