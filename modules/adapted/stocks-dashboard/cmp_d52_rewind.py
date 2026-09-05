# -*- coding: utf-8 -*-
"""Same-date comparison: Trendlyne REWIND 2026-06-12 (123 names) vs OUR 2026-06-12 (123 syms).
Rewind uses full company names -> map via bin meta names + alias. Apples-to-apples (no date gap)."""
import json,gzip,re
D=json.loads(gzip.decompress(open('docs/sf_stock_data.bin','rb').read()))
META=D['meta'];data=D['data']
mine=json.load(open('scripts/_mine_d52.json'))
OUR=set(x[0] for x in mine['2026-06-12'])

TLREW=["Adani Enterprises Ltd.","Adani Ports & Special Economic Zone Ltd.","Aegis Logistics Ltd.",
"AIA Engineering Ltd.","Ajanta Pharma Ltd.","GE Vernova T&D India Ltd.","Apar Industries Ltd.",
"Apollo Hospitals Enterprise Ltd.","Asian Paints Ltd.","Aurobindo Pharma Ltd.","Axis Bank Ltd.",
"Bajaj Auto Ltd.","Bharat Forge Ltd.","Biocon Ltd.","Bosch Ltd.","Zydus Lifesciences Ltd.",
"Caplin Point Laboratories Ltd.","Carborundum Universal Ltd.","CCL Products India Ltd.",
"Capri Global Capital Ltd.","Chennai Petroleum Corporation Ltd.","Coal India Ltd.",
"CG Power and Industrial Solutions Ltd.","Cummins India Ltd.","Divi's Laboratories Ltd.",
"Dr. Reddy's Laboratories Ltd.","Elgi Equipments Ltd.","Exide Industries Ltd.","Schaeffler India Ltd.",
"Federal Bank Ltd.","GMR Airports Ltd.","Granules India Ltd.","Grasim Industries Ltd.",
"Himadri Speciality Chemical Ltd.","Sammaan Capital Ltd.","Vodafone Idea Ltd.","IFCI Ltd.",
"IndusInd Bank Ltd.","Ipca Laboratories Ltd.","Jammu & Kashmir Bank Ltd.",
"J B Chemicals & Pharmaceuticals Ltd.","JSW Energy Ltd.","JSW Steel Ltd.",
"Kalpataru Projects International Ltd.","KEI Industries Ltd.","Kirloskar Oil Engines Ltd.",
"Larsen & Toubro Ltd.","Lupin Ltd.","Bank of Maharashtra","Manappuram Finance Ltd.","Marico Ltd.",
"Minda Corporation Ltd.","MMTC Ltd.","Samvardhana Motherson International Ltd.",
"Navin Fluorine International Ltd.","Nestle India Ltd.","NMDC Ltd.","Pidilite Industries Ltd.",
"Radico Khaitan Ltd.","Siemens Ltd.","Solar Industries India Ltd.","Sun Pharmaceutical Industries Ltd.",
"Tata Communications Ltd.","Thermax Ltd.","Timken India Ltd.","Titan Company Ltd.",
"Torrent Pharmaceuticals Ltd.","Usha Martin Ltd.","Vardhman Textiles Ltd.","Welspun Corp Ltd.",
"Welspun Living Ltd.","YES Bank Ltd.","Zydus Wellness Ltd.","Adani Energy Solutions Ltd.",
"Dr. Lal Pathlabs Ltd.","Lloyds Metals & Energy Ltd.","PTC Industries Ltd.","RBL Bank Ltd.",
"Varun Beverages Ltd.","Laurus Labs Ltd.","BSE Ltd.","Au Small Finance Bank Ltd.",
"Aditya Birla Capital Ltd.","General Insurance Corporation of India",
"Nippon Life India Asset Management Ltd.","Tube Investments of India Ltd.","Aster DM Healthcare Ltd.",
"Bandhan Bank Ltd.","Adani Green Energy Ltd.","Polycab India Ltd.","Gujarat Fluorochemicals Ltd.",
"Angel One Ltd.","Gland Pharma Ltd.","Craftsman Automation Ltd.","Shyam Metalics and Energy Ltd.",
"Sona BLW Precision Forgings Ltd.","Krishna Institute of Medical Sciences Ltd.",
"Vijaya Diagnostic Centre Ltd.","Acutaas Chemicals Ltd.","Aditya Birla Sun Life AMC Ltd.",
"FSN E-Commerce Ventures Ltd.","Anand Rathi Wealth Ltd.","Data Patterns (India) Ltd.",
"Syrma SGS Technology Ltd.","Netweb Technologies India Ltd.","R R Kabel Ltd.",
"Nuvama Wealth Management Ltd.","Honasa Consumer Ltd.","Tata Technologies Ltd.",
"Allied Blenders & Distillers Ltd.","Emcure Pharmaceuticals Ltd.","Premier Energies Ltd.",
"ACME Solar Holdings Ltd.","Niva Bupa Health Insurance Company Ltd.","Sai Life Science Ltd.",
"Ather Energy Ltd.","Belrise Industries Ltd.","Leela Palaces Hotels & Resorts Ltd.",
"Siemens Energy India Ltd.","Anthem Biosciences Ltd.","Aditya Infotech Ltd.",
"Emmvee Photovoltaic Power Ltd.","Piramal Finance Ltd."]

ALIAS={ # full-name(lower) -> our symbol, only where meta-name match fails
"ge vernova t and d india ltd":"GVT&D","siemens energy india ltd":"ENRIN","larsen and toubro ltd":"LT",
"vodafone idea ltd":"IDEA","welspun corp ltd":"WELCORP","tube investments of india ltd":"TIINDIA",
"samvardhana motherson international ltd":"MOTHERSON","bank of maharashtra":"MAHABANK",
"j b chemicals and pharmaceuticals ltd":"JBCHEPHARM","caplin point laboratories ltd":"CAPLIPOINT",
"general insurance corporation of india":"GICRE","nippon life india asset management ltd":"NAM-INDIA",
"kalpataru projects international ltd":"KPIL","lloyds metals and energy ltd":"LLOYDSME",
"adani energy solutions ltd":"ADANIENSOL","navin fluorine international ltd":"NAVINFLUOR",
"shyam metalics and energy ltd":"SHYAMMETL","sona blw precision forgings ltd":"SONACOMS",
"himadri speciality chemical ltd":"HSCL","aditya birla sun life amc ltd":"ABSLAMC",
"fsn e commerce ventures ltd":"NYKAA","krishna institute of medical sciences ltd":"KIMS",
"leela palaces hotels and resorts ltd":"THELEELA","allied blenders and distillers ltd":"ABDL",
"niva bupa health insurance company ltd":"NIVABUPA","emmvee photovoltaic power ltd":"EMMVEE",
"acutaas chemicals ltd":"ACUTAAS","anthem biosciences ltd":"ANTHEM","aditya infotech ltd":"CPPLUS",
"r r kabel ltd":"RRKABEL","capri global capital ltd":"CGCL","data patterns india ltd":"DATAPATTNS",
"gujarat fluorochemicals ltd":"FLUOROCHEM","sammaan capital ltd":"SAMMAANCAP","varun beverages ltd":"VBL",
"vardhman textiles ltd":"VTL","welspun living ltd":"WELSPUNLIV","ptc industries ltd":"PTCIL",
"netweb technologies india ltd":"NETWEB","syrma sgs technology ltd":"SYRMA","nuvama wealth management ltd":"NUVAMA",
"premier energies ltd":"PREMIERENE","acme solar holdings ltd":"ACMESOLAR","sai life science ltd":"SAILIFE",
"ather energy ltd":"ATHERENERG","belrise industries ltd":"BELRISE","kalpataru projects":"KPIL"}

def norm(s):
    s=s.lower().replace('&','and')
    s=re.sub(r'[^a-z0-9 ]',' ',s)
    s=re.sub(r'\b(ltd|limited|the)\b',' ',s)
    return re.sub(r'\s+','',s)

NAME2SYM={}
for sym,m in META.items():
    for cand in (norm(sym),norm(m.get('name',''))):
        if cand and cand not in NAME2SYM: NAME2SYM[cand]=sym

def resolve(name):
    a=re.sub(r'[^a-z0-9 ]',' ',name.lower().replace('&','and')); a=re.sub(r'\s+',' ',a).strip()
    if a in ALIAS: return ALIAS[a]
    k=norm(name)
    return NAME2SYM.get(k)

tl=set();unres=[]
for nm in TLREW:
    s=resolve(nm)
    if s:tl.add(s)
    else:unres.append(nm)

print("TL rewind 2026-06-12: %d names -> %d syms (%d unresolved)"%(len(TLREW),len(tl),len(unres)))
print("OUR 2026-06-12: %d syms"%len(OUR))
print("\nMATCH: %d / %d  (%.1f%% of TL)"%(len(tl&OUR),len(tl),100*len(tl&OUR)/len(tl)))
print("\nTL has, OURS missing:",sorted(tl-OUR))
print("\nOURS has, TL missing:",sorted(OUR-tl))
print("\nUNRESOLVED:",unres)
