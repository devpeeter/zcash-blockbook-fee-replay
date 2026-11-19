"""Read an independent, confirmed fee for the exact Blockbook transaction and block."""
import argparse
import gzip
import json
import sys
from decimal import Decimal
from pathlib import Path
from urllib.request import Request, urlopen
from fee_receipt import http_lookup, require

def reference(api, rpc, txid, captured_block=None):
    normal=http_lookup(api)("tx/"+txid)
    height, block_hash=normal["blockHeight"], normal["blockHash"]
    require(normal["txid"]==txid and normal["confirmations"]>0, "Expected a confirmed transaction")
    def call(method, params):
        body=json.dumps({"jsonrpc":"2.0","id":1,"method":method,"params":params}).encode()
        with urlopen(Request(rpc,data=body,headers={"Content-Type":"application/json"}),timeout=20) as r:
            d=json.load(r,parse_float=Decimal)
        require(d.get("id")==1 and not d.get("error"), "Independent node refused "+method)
        return d["result"]
    if captured_block:
        data=captured_block.read_bytes()
        if data.startswith(b"\x1f\x8b"):
            data=gzip.decompress(data)
        block=json.loads(data,parse_float=Decimal)["result"]
    else:
        require(call("getblockchaininfo",[])["chain"]=="main","Independent node is not on mainnet")
        block=call("getblock",[block_hash,3])
    require(block["hash"]==block_hash and block["height"]==height,"Mismatched independent block")
    matches=[t for t in block["tx"] if t["txid"]==txid]
    require(len(matches)==1,"Missing or duplicate independent transaction")
    value=matches[0].get("fee")
    require(type(value) in (int,Decimal),"Independent node returned no numeric fee")
    fee=Decimal(value)*100_000_000
    require(fee.is_finite() and fee>=0 and fee==int(fee),"Nonintegral independent fee")
    if not captured_block:
        require(call("getblockhash",[height])==block_hash,"Block is no longer active")
    addresses=[a for x in normal.get("vin",[])+normal.get("vout",[]) for a in x.get("addresses",[])
               if isinstance(a,str) and a.startswith(("t1","t3"))]
    require(bool(addresses),"No transparent address in this transaction for the watch-only wallet")
    return {"txid":txid,"height":height,"block_hash":block_hash,"address":addresses[0],
            "reference_source":"saved independent Zebra RPC response" if captured_block else "live independent Zebra RPC",
            "blockbook_zat":str(normal["fees"]),"independent_zat":str(int(fee))}
if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("api"); p.add_argument("rpc"); p.add_argument("txid")
    p.add_argument("--captured-block",type=Path,help="Previously retrieved independent getblock verbosity 3 response")
    args=p.parse_args()
    try:
        print(json.dumps(reference(args.api,args.rpc,args.txid,args.captured_block)))
    except (OSError,ValueError,KeyError,TypeError) as e:
        print(json.dumps({"status":"UNAVAILABLE","reason":str(e)}));sys.exit(1)
