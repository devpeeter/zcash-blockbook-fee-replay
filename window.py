"""Audit a fixed Zcash mainnet block range. Replays locally by default; --fetch downloads public data."""
import argparse
import gzip
import hashlib
import json
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from fee_receipt import get_receipt, amount, require
from block_integrity import check_native_header, transaction_root
from transaction_bytes import check_transaction

ZEBRA = "https://zcash-mainnet-zebrad.gateway.tatum.io"
PROVIDER = "https://docs-demo.zec-mainnet.quiknode.pro"
ROOT = Path(__file__).resolve().parent

def fetch(url, method=None, params=None):
    payload = None if method is None else json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
    headers = {"Accept":"application/json","Content-Type":"application/json"}
    for attempt in range(2):
        try:
            with urlopen(Request(url, data=payload, headers=headers), timeout=30) as response:
                body = response.read()
            obj=json.loads(body,parse_float=Decimal)
            if method:
                require(obj.get("id")==1 and not obj.get("error"),"Failed RPC method "+method)
            return body
        except HTTPError as error:
            if attempt or error.code not in (429,502,503,504): raise
            time.sleep(min(40, max(1,int(error.headers.get("Retry-After","5")))))
        except URLError:
            if attempt: raise
            time.sleep(2)
    raise RuntimeError("No response")

def record(path, live_request=None):
    if path.exists():
        data=gzip.decompress(path.read_bytes())
    else:
        if live_request is None: raise FileNotFoundError(str(path))
        data=live_request()
        path.parent.mkdir(parents=True,exist_ok=True)
        temporary=path.with_suffix(".tmp")
        temporary.write_bytes(gzip.compress(data,mtime=0))
        temporary.replace(path)
    return json.loads(data,parse_float=Decimal),hashlib.sha256(data).hexdigest()

def pages(block_hash, height, folder, live):
    response, dig=record(folder/'blockbook'/f'{height}.json.gz',
        (lambda: fetch(PROVIDER+'/api/v2/block/'+block_hash)) if live else None)
    require(response['hash']==block_hash and response['height']==height,'Blockbook block mismatch')
    rows=list(response['txs'])
    hashes=[dig]
    for page in range(2,int(response.get('totalPages',1))+1):
        res,pdigest=record(folder/'blockbook'/f'{height}-{page}.json.gz',
            (lambda: fetch(f'{PROVIDER}/api/v2/block/{block_hash}?page={page}')) if live else None)
        require(res['hash']==block_hash and res['page']==page,'Blockbook page mismatch')
        rows.extend(res['txs'])
        hashes.append(pdigest)
    require(len(rows)==response['txCount'],'Incomplete Blockbook transaction list')
    require(transaction_root([row['txid'] for row in rows]) == response['merkleRoot'],
            'Blockbook transaction list disagrees with its Merkle root')
    return rows,hashes

def native_zatoshis(value):
    require(type(value) in (int, Decimal), 'Missing numeric node amount')
    zatoshis = Decimal(value) * 100_000_000
    require(zatoshis.is_finite() and zatoshis >= 0 and int(zatoshis) == zatoshis,
            'Node returned an invalid zatoshi amount')
    return int(zatoshis)

def at_height(h,folder,live,zebra_files=None):
    zp=(zebra_files or folder/'zebra')/f'{h}.json.gz'
    doc,zdigest=record(zp,(lambda:fetch(ZEBRA,'getblock',[str(h),3])) if live else None)
    z=doc['result']
    require(z['height']==h,'Independent Zebra returned another height')
    bh=z['hash']
    native_path=folder/'provider-native'/f'{h}.json.gz'
    with ThreadPoolExecutor(max_workers=2) as jobs:
        one=jobs.submit(pages,bh,h,folder,live)
        two=jobs.submit(record,native_path,(lambda:fetch(PROVIDER,'getblock',[bh,2])) if live else None)
        normalized,bdigests=one.result()
        source,ndigest=two.result()
    native=source['result']
    require(native['height']==h and native['hash']==bh, 'Provider native block mismatch')
    ids=[t['txid'] for t in z['tx']]
    require(len(ids)==len(set(ids)) and ids==[t['txid'] for t in normalized]==[t['txid'] for t in native['tx']],
            'Cross-provider transaction list or ordering mismatch')
    root = transaction_root(ids)
    check_native_header(z, root)
    check_native_header(native, root)
    results=[]
    for ref,view,raw in zip(z['tx'], normalized, native['tx']):
        txid=ref['txid']
        row={"height":h,"txid":txid}
        require(raw['hex'] == ref['hex'], 'Node transaction bytes differ across providers')
        coinbase = any('coinbase' in i for i in ref['vin'])
        require(coinbase == (txid == ids[0]) == any('coinbase' in i for i in raw['vin']),
                'Coinbase identity or position mismatch')
        if coinbase:
            check_transaction(raw)
            row['status']='COINBASE'
        else:
            try:
                ref_zat = native_zatoshis(ref.get('fee'))
                require(len(view['vin']) == len(ref['vin']), 'Independent input count mismatch')
                for displayed, spent in zip(view['vin'], ref['vin']):
                    require((displayed['txid'], displayed.get('vout', 0)) == (spent['txid'], spent['vout'])
                            and amount(displayed['value']) == native_zatoshis(spent['prevout']['value']),
                            'Resolved transparent input disagrees with the independent Zebra prevout')
                require(view['blockHash']==raw['blockhash']==ref['blockhash']==bh and view['blockHeight']==h,
                        'Cross-provider transaction block mismatch')
                row['original_zat']=amount(view['fees'])
                row['reference_zat']=int(ref_zat)
                routes={'tx/'+txid:view,'tx-specific/'+txid:raw,'block-index/'+str(h):{'blockHash':bh}}
                row['corrected_zat']=amount(get_receipt(routes.__getitem__,txid)['fees'])
                if row['corrected_zat']!=row['reference_zat']: row['status']='FAIL'
                elif row['original_zat']>row['reference_zat']: row['status']='OVERSTATED'
                elif row['original_zat']<row['reference_zat']: row['status']='UNDERSTATED'
                else: row['status']='MATCH'
                row['transparent_address']=any(isinstance(a,str) and a.startswith(('t1','t3'))
                     for v in view.get('vin',[])+view.get('vout',[]) for a in v.get('addresses',[]))
            except (KeyError,ValueError,TypeError,IndexError) as error:
                row.update(status='UNVERIFIABLE',reason=str(error))
        results.append(row)
    return {'height':h,'hash':bh,'previous':z['previousblockhash'],'time':z['time'],
            'sha256':{'zebra':zdigest,'blockbook':bdigests,'provider_native':ndigest}},results

def audit(folder,start,count,live,anchor=None):
    blocks,rows=[],[]
    for h in range(start,start+count):
        header,items=at_height(h,folder,live)
        require(not blocks or header['previous']==blocks[-1]['hash'], 'Block range changed at '+str(h))
        blocks.append(header)
        rows.extend(items)
    if anchor: require(blocks[-1]['hash']==anchor,'Frozen range anchor mismatch')
    require(len({r['txid'] for r in rows})==len(rows), 'Duplicate transaction in range')
    counts=Counter(r['status'] for r in rows)
    badrows=[r for r in rows if r['status'] in ('OVERSTATED','UNDERSTATED')]
    verdict='FAIL' if counts['FAIL'] else 'INCOMPLETE' if counts['UNVERIFIABLE'] else 'PASS' if badrows else 'NO_DISCREPANCY'
    return {'status':verdict,'from_height':start,'to_height':start+count-1,'blocks':len(blocks),
            'block_sequence':blocks,'counts':dict(counts),'transactions':rows,
            'non_coinbase':len(rows)-counts['COINBASE'],'original_discrepancies':len(badrows),
            'mismatches_with_a_transparent_address':sum(r.get('transparent_address',False) for r in badrows),
            'original_zero_positive_reference':sum(r['original_zat']==0<r['reference_zat'] for r in badrows)}

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--captures',type=Path,default=ROOT/'captures')
    parser.add_argument('--start',type=int,default=3584389)
    parser.add_argument('--count',type=int,default=100)
    parser.add_argument('--anchor',default='0000000000a7c779f034142ed7430b24cb820dfb7cc5c26bab01ed07ee9e4ba5')
    parser.add_argument('--fetch',action='store_true',help='Download missing records. Use a new captures directory to repeat live.')
    o=parser.parse_args()
    require(o.start>0 and o.count>0,'Invalid range')
    result=audit(o.captures,o.start,o.count,o.fetch,o.anchor)
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['status']=='PASS' else 1)
