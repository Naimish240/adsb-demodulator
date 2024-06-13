from rtlsdr import RtlSdr
import numpy as np
import pyModeS as pms
from prettytable import PrettyTable
import os
from datetime import datetime
import pickle
import argparse


database = {}


class Airplane(object):
    def __init__(self, icao):
        self.icao = icao
        self.messages = []
        self.vel = ""
        self.even_pos = ''
        self.odd_pos = ''
        self.callsign = ''
        self.last_ts = 0
    
    def update_message(self, msg):
        icao, df, tc, ooe = message_info(msg)

        assert icao == self.icao

        self.messages.append(msg)
        self.last_ts = datetime.now().strftime("%H:%M:%S")

        if tc == 4:
            self.callsign = pms.adsb.callsign(msg)
        elif tc == 19:
            self.vel = msg
        elif tc == 11:
            if ooe == '1':
                self.odd_pos = msg
            else:
                self.even_pos = msg

    def position(self):
        if self.even_pos and self.odd_pos:
            return pms.adsb.position(self.odd_pos, self.even_pos, 0, 1)
        return 0, 0

    def velocity(self):
        if self.vel:
            return pms.adsb.velocity(self.vel)
        return 0, 0, 0, 0

    def details(self):
        lat, lon = self.position()
        speed, heading, vertical_rate, speed_type = self.velocity()

        return [
            self.icao,
            self.callsign,
            lat,
            lon,
            speed,
            heading,
            vertical_rate,
            speed_type,
            self.last_ts,
            len(self.messages)
        ]


def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')


def connect():
    sdr = RtlSdr()
    fs = 2000000
    sdr.set_sample_rate(fs)
    sdr.set_center_freq(1090e6)
    sdr.set_gain(38.6)
    return sdr


def disconnect(sdr):
    sdr.close()


def get_samples(sdr, N_Samples):
    samples = sdr.read_samples(N_Samples)
    y = abs(samples)
    return y


def bool2Hex(lst):
    tmp =  ''.join(['1' if x else '0' for x in lst])
    return hex(int(tmp,2))[2:]


def detectPreambleXcorr(chunk,corrthresh):    
    preamble = np.array([1, 0, 1, 0, 0, 0, 0, 1, 0, 1, 0, 0, 0, 0, 0, 0]) - 0.25
    
    if preamble.shape != chunk.shape:
        return 0

    chunk_mean = np.mean(chunk)
    c = np.array(chunk) - chunk_mean
    b = c * preamble
    numerator = np.sum(b)         
    
    a1 = np.linalg.norm(c)            
    a2 = np.linalg.norm(preamble)      
    
    denominator = a1*a2
    
    crossCorr = numerator/denominator

    if (crossCorr>corrthresh):
        return 1
    else:
        return 0


def identify_messages(y):
    y_mean = np.mean(y)
    y_std=np.std(y)

    alpha = 5
    sig_thresh = y_mean + alpha*y_std
    idx_sig = np.nonzero(y > sig_thresh)[0]
    idx_corr = []

    for n in idx_sig:
        x = abs(y[n:n+16])
        a = detectPreambleXcorr(x,0.5)
        if a == 1:
            idx_corr.append(n)

    msgs = []
    
    for i in range(len(idx_corr)):
        row = abs(y[idx_corr[i]:idx_corr[i]+16+112*2])
        if len(row) != 240:
            continue
        msgs.append(row)
    
    msgs = np.vstack(msgs)


    output = []
    for n in range(msgs.shape[0]):
        bits = msgs[n,16::2] > msgs[n,17::2]
        msg = bool2Hex(bits)
        crc = pms.crc(msg)
        crc_str = str(crc).encode()
        crc_bool = np.frombuffer(crc_str, dtype=np.int8) - np.int8(48)
        
        if (all (crc_bool==0)):
            output.append(msg)

        else :
            crc = pms.crc(msg[:14])
            crc_str = str(crc).encode()
            crc_bool = np.frombuffer(crc_str, dtype=np.int8) - np.int8(48)
            if (all (crc_bool==0)):
                output.append(msg)

    return output


def message_info(msg):
    icao_address = pms.common.icao(msg)
    df = pms.common.df(msg)
    tc = pms.common.typecode(msg)
    odd_or_even = pms.hex2bin(msg)[53]

    return icao_address, df, tc, odd_or_even


def print_table(table):
    tab = PrettyTable(table[0])
    tab.add_rows(table[1:])
    print(tab)


def main(save_db=False):
    sdr = connect()
    while True:
        try:
            y = get_samples(sdr, 2048000 * 2)
            messages = identify_messages(y)

            for message in messages:
                icao = pms.common.icao(message)

                if not icao:
                    continue

                if icao not in database.keys():
                    new_record = Airplane(icao)
                    new_record.update_message(message)
                    database[icao] = new_record
                
                else:
                    record = database[icao]
                    record.update_message(message)
            
            cols = 'icao,callsign,lat,lon,speed,heading,vertical_rate,speed_type,last_message,messages'.split(',')
            table = [cols]
            
            for icao in database.keys():
                table.append(database[icao].details())

            clear_screen()
            print_table(table)
            print("Press `ctrl+c` to exit")

            if save_db:
                with open('dump.p', 'wb') as db:
                    pickle.dump(database, db)

        except KeyboardInterrupt:
            disconnect(sdr)
            return None

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--save', action='store_true')
    args = parser.parse_args()

    main(save_db=args.save)