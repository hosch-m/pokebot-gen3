import os
import json
import time
import struct
import atexit
import logging
from pymem import Pymem
import win32gui, win32process

from modules.Files import ReadFile

log = logging.getLogger(__name__)

# https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_data_substructures_(Generation_III)#Substructure_order
substructs = ['GAEM', 'GAME', 'GEAM', 'GEMA', 'GMAE', 'GMEA', 'AGEM', 'AGME', 'AEGM', 'AEMG', 'AMGE', 'AMEG',
              'EGAM', 'EGMA', 'EAGM', 'EAMG', 'EMGA', 'EMAG', 'MGAE', 'MGEA', 'MAGE', 'MAEG', 'MEGA', 'MEAG']

moves = json.loads(ReadFile('./modules/data/moves.json'))
names = json.loads(ReadFile('./modules/data/names.json'))
natures = json.loads(ReadFile('./modules/data/natures.json'))
nat_ids = json.loads(ReadFile('./modules/data/nat-ids.json'))
item_list = json.loads(ReadFile('./modules/data/items.json'))
exp_groups = json.loads(ReadFile('./modules/data/exp-groups.json'))
pokemon_list = json.loads(ReadFile('./modules/data/pokemon.json'))
location_list = json.loads(ReadFile('./modules/data/locations.json'))
hidden_powers = json.loads(ReadFile('./modules/data/hidden-powers.json'))

# https://bulbapedia.bulbagarden.net/wiki/Character_encoding_(Generation_III)
char_maps = json.loads(ReadFile('./modules/data/char-maps.json'))
char_map_i = char_maps['i']
char_map_j = char_maps['j']

session_count = 0 # TODO temporary for testing

def GetPointer(proc, base, offsets):
    """
    This function will "follow a bouncing ball" of offsets and return a pointer to the desired memory location.
    When mGBA is launched, the locations of the GBA memory domains will be in a random location, this ensures that
    the same memory domain can be found reliably, every time.
    For more information check out: https://www.youtube.com/watch?v=YaFlh2pIKAg

    :param proc: an initialised Pymem class
    :param base: base address
    :param offsets: memory offsets to follow
    :return: memory pointer to the desired address
    """

    addr = proc.read_longlong(base)
    for i in offsets:
        if i != offsets[-1]:
            addr = proc.read_longlong(addr + i)
    return addr + offsets[-1]

class emulator:
    def __game(self):
        match self.game_code[0:3]: # Game release
            case 'AXV':
                self.game, self.sym_file = 'Pokémon Ruby', 'pokeruby.sym'
            case 'AXP':
                self.game, self.sym_file = 'Pokémon Sapphire', 'pokesapphire.sym'
            case 'BPE':
                self.game, self.sym_file = 'Pokémon Emerald', 'pokeemerald.sym'
            case 'BPR':
                self.game, self.sym_file = 'Pokémon FireRed', 'pokefirered.sym'
            case 'BPG':
                self.game, self.sym_file = 'Pokémon LeafGreen', 'pokeleafgreen.sym'
            case _:
                self.game, self.sym_file = None, None
        match self.game_code[3]: # Game language
            case 'E':
                self.charmap = char_map_i
            case 'J':
                self.charmap = char_map_j
            case 'D':
                self.charmap = char_map_i
            case 'S':
                self.charmap = char_map_i
            case 'F':
                self.charmap = char_map_i
            case 'I':
                self.charmap = char_map_i

    def __symbols(self):
        if self.sym_file:
            self.symbols = {}
            for s in open(f'modules/data/symbols/{self.sym_file}').readlines():
                self.symbols[s.split(' ')[3].strip()] = {
                    'addr': int(s.split(' ')[0], 16),
                    'type': str(s.split(' ')[1]),
                    'size': int(s.split(' ')[2], 16)
                }
        else:
            self.symbols = None

    def __init__(self, pid):
        self.proc = Pymem(pid)
        self.p_EWRAM = GetPointer(self.proc, self.proc.base_address + 0x02849A28,
                                  offsets=[0x40, 0x58, 0x8, 0x28, 0x0])
        self.p_IWRAM = GetPointer(self.proc, self.proc.base_address + 0x02849A28,
                                  offsets=[0x40, 0x58, 0x138, 0x240, 0x8, 0x30, 0x0])
        self.p_ROM = GetPointer(self.proc, self.proc.base_address + 0x02849A28,
                                offsets=[0x20, 0x58, 0x158, 0x240, 0x8, 0x38, 0x0])
        self.p_Input = GetPointer(self.proc, self.proc.base_address + 0x02849A28,
                                  offsets=[0x20, 0x58, 0x6D8, 0x420, 0x168, 0x420, 0xDE4])
        self.p_Framecount = GetPointer(self.proc, self.proc.base_address + 0x02849A28,
                                       offsets=[0x40, 0x58, 0x10, 0x1C0, 0x0, 0x90, 0xF0])
        self.game_code = self.proc.read_bytes(self.p_ROM + 0xAC, 4).decode('utf-8')
        self.__game()
        self.__symbols()

while True:
    log.info('Click on an mGBA instance to attach bot to...')
    fg = win32gui.GetForegroundWindow()
    title = win32gui.GetWindowText(fg)
    tid, pid = win32process.GetWindowThreadProcessId(fg)

    if 'mGBA' in title:
        mGBA = emulator(pid)
        if mGBA.game:
            log.info(f'Bot successfully attached to mGBA PID {pid}!')
            log.info(f'Detected game: {mGBA.game} ({mGBA.game_code})')
            break
        else:
            log.error('Unsupported ROM detected!')
            input('Press enter to continue...')
            os._exit(1)
    time.sleep(0.5)

def ReadSymbol(name: str, offset: int = 0, size: int = 0):
    """
    This function uses the symbol tables from the Pokémon decompilation projects found here: https://github.com/pret
    Symbol tables are loaded and parsed as a dict in the `emulator` class, the .sym files for each game can be found
    in `modules/data/symbols`.

    Format of symbol tables:
    `020244ec g 00000258 gPlayerParty`
    020244ec     - memory address
    g            - (l,g,,!) local, global, neither, both
    00000258     - size in bytes (base 16) (0x258 = 600 bytes)
    gPlayerParty - name of the symbol

    GBA memory domains: https://corrupt.wiki/consoles/gameboy-advance/bizhawk-memory-domains
    0x02000000 - 0x02030000 - 256 KB EWRAM (general purpose RAM external to the CPU)
    0x03000000 - 0x03007FFF - 32 KB IWRAM (general purpose RAM internal to the CPU)
    0x08000000 - 0x???????? - Game Pak ROM (0 to 32 MB)

    :param name: name of the symbol to read
    :param offset: (optional) add n bytes to the address of symbol
    :param size: (optional) override the size to read n bytes
    :return: byte data
    """
    sym_addr = mGBA.symbols[name]['addr']
    match sym_addr >> 24:
        case 2: addr = mGBA.p_EWRAM + (sym_addr - mGBA.symbols['EWRAM_START']['addr'])
        case 3: addr = mGBA.p_IWRAM + (sym_addr - mGBA.symbols['IWRAM_START']['addr'])
        case 8: addr = mGBA.p_ROM + (sym_addr - mGBA.symbols['Start']['addr'])
        case _: return None
    if size > 0:
        return mGBA.proc.read_bytes(addr + offset, size)
    else:
        return mGBA.proc.read_bytes(addr + offset, mGBA.symbols[name]['size'])

def GetFrameCount():
    """
    Get the current mGBA frame count since the start of emulation.

    :return: frame count (int)
    """
    return struct.unpack('<I', mGBA.proc.read_bytes(mGBA.p_Framecount, length=4))[0]

def FacingDir(dir: int):
    match dir:
        case 34: return 'Up'
        case 68: return 'Right'
        case 17: return 'Down'
        case 51: return 'Left'
    return None

try:
    if mGBA.game in ['Pokémon Emerald', 'Pokémon FireRed', 'Pokémon LeafGreen']:
        gSaveBlock2Ptr = ReadSymbol('gSaveBlock2Ptr')
        p_Trainer = mGBA.p_EWRAM + (struct.unpack('<I', ReadSymbol('gSaveBlock2Ptr'))[0] - mGBA.symbols['EWRAM_START']['addr'])
        b_Trainer = mGBA.proc.read_bytes(p_Trainer, length=14)
    else:
        b_Trainer = ReadSymbol('gSaveBlock2', 14)
except Exception as e:
    log.exception(str(e))


def ParseString(text: bytes):
    string = ''
    for i in text:
        c = int(i) - 16
        if c < 0 or c > len(mGBA.charmap):
            string = string + ' '
        else:
            string = string + mGBA.charmap[c]
    return string.strip()

# https://bulbapedia.bulbagarden.net/wiki/Save_data_structure_(Generation_III)
def GetTrainer():
    b_gTasks = ReadSymbol('gTasks')
    b_gObjectEvents = ReadSymbol('gObjectEvents')
    trainer = {
        'name': ParseString(b_Trainer[0:7]),
        'gender': 'girl' if int(b_Trainer[8]) else 'boy',
        'tid': int(struct.unpack('<H', b_Trainer[10:12])[0]),
        'sid': int(struct.unpack('<H', b_Trainer[12:14])[0]),
        'state': int(b_gTasks[87]),
        'map': (int(b_gTasks[89]), int(b_gTasks[88])),
        'coords': (int(b_gObjectEvents[16]) - 7, int(b_gObjectEvents[18]) - 7),
        'facing': FacingDir(int(b_gObjectEvents[24]))
    }
    return trainer

def SpeciesName(id: int):
    if id > len(names):
        return ''
    return names[id - 1]

def NationalDexID(id: int):
    if id <= 251:
        return id
    if id >= 413:
        return 201
    ix = id - 277
    if ix < len(nat_ids):
        return nat_ids[ix]
    return 0

def Language(value: int):
    match value:
        case 1: return 'Japanese'
        case 2: return 'English'
        case 3: return 'French'
        case 4: return 'Italian'
        case 5: return 'German'
        case 7: return 'Spanish'
    return None

def OriginGame(value: int):
    match value:
        case 1: return 'Sapphire'
        case 2: return 'Ruby'
        case 3: return 'Emerald'
        case 4: return 'FireRed'
        case 5: return 'LeafGreen'
        case 15: return 'Colosseum/XD'
    return None

def Markings(value: int):
    markings = {
        'circle': False,
        'square': False,
        'triangle': False,
        'heart': False
    }
    if value & (1 << 0): markings['circle'] = True
    if value & (1 << 1): markings['square'] = True
    if value & (1 << 2): markings['triangle'] = True
    if value & (1 << 3): markings['heart'] = True
    return markings

def Status(value: int):
    status = {
        'sleep': value & 0x7,
        'poison': False,
        'burn': False,
        'freeze': False,
        'paralysis': False,
        'badPoison': False
    }
    if value & (1 << 3): status['poison'] = True
    if value & (1 << 4): status['burn'] = True
    if value & (1 << 5): status['freeze'] = True
    if value & (1 << 6): status['paralysis'] = True
    if value & (1 << 7): status['badPoison'] = True
    return status

def Origins(value: int):
    origins = {
        'metLevel': value & 0x7F,
        'hatched': False,
        'game': OriginGame((value >> 7) & 0xF),
        'ball': item_list[(value >> 11) & 0xF]
    }
    if origins['metLevel'] == 0: origins['hatched'] = True
    return origins

def Pokerus(value: int):
    pokerus = {
        'days': value & 0xF,
        'strain': value >> 4,
    }
    return pokerus

def DecryptSubSection(data: bytes, key: int):
    a = struct.unpack('<I', data[0:4])[0] ^ key
    b = struct.unpack('<I', data[4:8])[0] ^ key
    c = struct.unpack('<I', data[8:12])[0] ^ key
    return struct.pack('<III', a, b, c)

# https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_data_structure_(Generation_III)
def ParsePokemon(b_Pokemon: bytes):
    flags = int(b_Pokemon[19])
    pid = struct.unpack('<I', b_Pokemon[0:4])[0]
    ot = struct.unpack('<I', b_Pokemon[4:8])[0]
    tid = int(struct.unpack('<H', b_Pokemon[4:6])[0])
    sid = int(struct.unpack('<H', b_Pokemon[6:8])[0])

    # Unpack data substructures
    # https://bulbapedia.bulbagarden.net/wiki/Pok%C3%A9mon_data_substructures_(Generation_III)
    key = ot ^ pid
    data = b_Pokemon[32:80]
    order = pid % 24
    order_string = substructs[order]
    sections = {}
    for i in range(0, 4):
        section = order_string[i]
        sectiondata = data[(i * 12):((i + 1) * 12)]
        decr = DecryptSubSection(sectiondata, key)
        sections[section] = decr
    id = int(struct.unpack('<H', sections['G'][0:2])[0])

    # Unpack moveset
    pokemon_moves = []
    pokemon_pp = []
    for i in range(0, 4):
        move_id = int(struct.unpack('<H', sections['A'][(i * 2):((i + 1) * 2)])[0])
        if id == 0:
            continue
        pokemon_moves.append(moves[move_id])
        pokemon_pp.append(int(sections['A'][(i + 8)]))

    # Unpack IVs
    b_ivs = int(struct.unpack('<I', sections['M'][4:8])[0])
    iv_bitstring = str(str(bin(b_ivs)[2:])[::-1] + '00000000000000000000000000000000')[0:32]
    ivs = {
        'hp': int(iv_bitstring[0:5], 2),
        'attack': int(iv_bitstring[5:10], 2),
        'defense': int(iv_bitstring[10:15], 2),
        'speed': int(iv_bitstring[15:20], 2),
        'spAttack': int(iv_bitstring[20:25], 2),
        'spDefense': int(iv_bitstring[25:30], 2),
    }
    iv_sum = (ivs['hp'] + ivs['attack'] + ivs['defense'] + ivs['speed'] + ivs['spAttack'] + ivs['spDefense'])

    item_id = int(struct.unpack('<H', sections['G'][2:4])[0])
    sv = int(tid ^ sid ^ struct.unpack('<H', b_Pokemon[0:2])[0] ^ struct.unpack('<H', b_Pokemon[2:4])[0])
    shiny = True if sv < 8 else False

    global session_count
    session_count += 1
    log.info(f'#{session_count:,} - SV {sv:,} {SpeciesName(id)}')

    pokemon = {
        'name': SpeciesName(id),
        'id': id,
        'natID': NationalDexID(id),
        'species': int(struct.unpack('<H', sections['G'][0:2])[0]),
        'personality': pid,
        'nature': natures[pid % 25],
        'language': Language(int(b_Pokemon[18])),
        'shinyValue': sv,
        'shiny': shiny,
        'ot': {
            'tid': tid,
            'sid': sid
        },
        'nickname': ParseString(b_Pokemon[8:18]),
        'isBadEgg': flags & 1,
        'hasSpecies': (flags >> 1) & 1,
        'isEgg': (flags >> 2) & 1,
        'level': int(b_Pokemon[84]),
        'expGroup': exp_groups[id - 1],
        'item': {
            'id': item_id,
            'name': item_list[item_id]
        },
        'friendship': int(sections['G'][9]),
        'moves': pokemon_moves,
        'pp': pokemon_pp,
        'markings': Markings(b_Pokemon[27]),
        'status': Status(int(struct.unpack('<I', b_Pokemon[80:84])[0])),
        'stats': {
            'hp': int(b_Pokemon[86]),
            'maxHP': int(b_Pokemon[88]),
            'attack': int(b_Pokemon[90]),
            'defense': int(b_Pokemon[92]),
            'speed': int(b_Pokemon[94]),
            'spAttack': int(b_Pokemon[96]),
            'spDefense': int(b_Pokemon[98])
        },
        'IVs': ivs,
        'IVSum': iv_sum,

        # Substruct G - Growth
        'experience': int(struct.unpack('<I', sections['G'][4:8])[0]),

        # Substruct A - Attacks

        # Substruct E - EVs & Condition
        'EVs': {
            'hp': int(sections['E'][0]),
            'attack': int(sections['E'][1]),
            'defence': int(sections['E'][2]),
            'speed': int(sections['E'][3]),
            'spAttack': int(sections['E'][4]),
            'spDefense': int(sections['E'][5])
        },
        'condition': {
            'cool': int(sections['E'][6]),
            'beauty': int(sections['E'][7]),
            'cute': int(sections['E'][8]),
            'smart': int(sections['E'][9]),
            'tough': int(sections['E'][10]),
            'feel': int(sections['E'][11])
        },

        # Substruct M - Miscellaneous
        'origins': Origins(int(struct.unpack('<H', sections['M'][2:4])[0])),
        'pokerus': Pokerus(int(sections['M'][1])),
    }
    return pokemon

def GetParty():
    party = {}
    b_gPlayerParty = ReadSymbol('gPlayerParty')
    party_count = int.from_bytes(ReadSymbol('gPlayerPartyCount'))
    if party_count:
        for p in range(party_count):
            o = p*100
            party[p] = ParsePokemon(b_gPlayerParty[o:o+100])
        return party
    return None

def GetOpponent():
    b_gEnemyParty = ReadSymbol('gEnemyParty')
    return ParsePokemon(b_gEnemyParty[:100])

last_opid = ReadSymbol('gEnemyParty', size=4)
def OpponentChanged():
    global last_opid
    opponent_pid = ReadSymbol('gEnemyParty', size=4)
    if opponent_pid != last_opid:
        last_opid = opponent_pid
        return True
    else:
        return False

def _exit():
    WriteInputs(0) # Clear inputs if bot is stopped
atexit.register(_exit)