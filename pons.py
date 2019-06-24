from bs4 import BeautifulSoup
import sys
import re
from random import shuffle 
import requests
from itertools import groupby,dropwhile,takewhile,zip_longest,chain
from textwrap import wrap
import ftfy
import urllib3
from verblist import verb_list
import string 
#theads!
from multiprocessing import Pool
from time import sleep

line_parbox='''\\parbox[t][][t]{{2cm}}{{\\normalfont {ich}\\\\{du}\\\\{er/sie/es}\\\\{wir}\\\\{ihr}\\\\{sie}}}'''

table_verb='''
%==={word}===
\\card{{\\normalfont \\Huge {word}}}{{
\\begin{{tabular}}{{lll}}
\\parbox[t][][t]{{2.0 cm}}{{\\normalfont \\raggedleft ich\\\\du\\\\er/sie/es\\\\wir\\\\ihr\\\\sie}} &    
{Präsens} &
{Präteritum}\\\\
\\end{{tabular}}
\\begin{{tabular}}{{l}}
\\parbox[t][][t]{{8cm}}{{}}\\\\
\\parbox[t][][t]{{8cm}}{{\\normalfont \\footnotesize 
{{example}} 
}}\\\\
\\end{{tabular}}
}}'''

def make_request(verb):
    r=None
    headers = {'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'}
    try:
        url="https://en.pons.com/verb-tables/german/{0}?&l=deen".format(verb)   
        #centralproxy.northgrum.com
        proxies = {'http': '134.223.230.151:80','https': '134.223.230.151:80'}
        r = requests.get(url, headers=headers,verify=False,timeout=100)
        sleep(2)
    except Exception as e:
        print('Error on line {}'.format(sys.exc_info()[-1].tb_lineno), type(e).__name__, e)
    return r


def parse(verb):

    
    text=""
    ret={}
    conjugations=['Präsens','Präteritum']
    #conjugations=['Präsens','Präteritum','Perfekt']
    try:
        r=make_request(verb)

        if r.status_code == 200:
            print('Processing..' + verb)
            html = r.text
            
            soup = BeautifulSoup(html, "html.parser")
            table=soup.find('div',{'id':"flection_table","class":"de"})
            
            '''out=[process_table(table.find(text=x).parent.nextSibling) for x in conjugations]'''
            tables={x:table.find(text=x).parent.nextSibling for x in conjugations}
            out={}
            out['word']=verb
            for key,table in tables.items():
                tds =[[x.text for x in y.findAll('td')] for y in table.findAll('tr')]
                ret={x[0]:" ".join(x[1:]) for x in tds}
                out[key]=line_parbox.format(**ret)
            text=table_verb.format(**out)     
            '''
            sel=soup.select('dl[data-translation]')
            textlist=list(chain.from_iterable([x.split('\n') for x in [re.sub(r'\n+','\n',x.text.strip()) for x in sel]]))
            textlist=[x for x in textlist if 'British English American English' not in x ]
            textlist=[x for x in [x.strip() for x in textlist] if len(x) > 0]
            textlist=[re.sub(r'\[','(',x) for x in textlist]
            textlist=[re.sub(r'\]',')',x) for x in textlist]
            out=table_verb.format(**{'word':verb,'example':"\n".join(textlist[0:10])})
            '''
            '''
            textlist=[x.split('\n') for x in [x.text.strip() for x in sel] ]
            textlist=[x for x in textlist if len(x) > 0]
            ids=soup.findAll(id=re.compile('Tdeen[0-9]*'))
            ids=[x for x in ids if x is not None]
            
            textlist=[x.text for x in ids]
            textlist=[x.replace('\n','').strip() for x in textlist]
            textlist=[x.replace('British English American English','') for x in textlist]
            textlist=[x.replace('\xa0Add to my favourites\xa0Preselect for export to vocabulary trainer\xa0View selected vocabulary','') for x in textlist]
            out[verb]=textlist
            '''
    except Exception as e:
        print('Error on line {}'.format(sys.exc_info()[-1].tb_lineno), type(e).__name__, e)
    return text

def main():
    #use with thread pools
    urllib3.disable_warnings()
    #shuffle(verb_list)
    #ret=parse('rennen')
    #print(ret)
    
    p = Pool(20)  # Pool tells how many at a time
    records = p.map(parse, verb_list)

    p.terminate()
    p.join()

    f=open("pons-check.tex","w",encoding='utf-8')
    for record in records:
        f.write (record)
    f.close()
    
if __name__ == "__main__":
    main()