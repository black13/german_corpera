from bs4 import BeautifulSoup
import sys
import re
from random import shuffle 
import itertools
import requests
from itertools import groupby
from itertools import dropwhile,takewhile
from verblist import verb_list
def group2(iterator, count):
    return list(itertools.imap(None, *([ iter(iterator) ] * count)))

def get_result_set(verb):
    url="http://en.wiktionary.org/wiki/{0}#Conjugation".format(verb)
    res = requests.get(url,verify=False)
    soup = BeautifulSoup(res.text,"html.parser")
    return soup

def get_meaning(parent):
    tag_list = [x for x in parent.find_next_siblings()]
    filt=list(takewhile(lambda t: 'Conjugation[edit]' not in t.text,tag_list))
    filt=list(dropwhile(lambda t: 'Verb[edit]' not in t.text,filt))
    text=[x.text for x in filt]
    return text
    #list((list(g) for _, g in groupby(l, key='Conjugation[edit]'.__ne__)))[0]

def get_conjugation(parent):
    tag_list = [x for x in parent.find_next_siblings()]
    filt=list(dropwhile(lambda t: 'Conjugation[edit]' not in t.text,tag_list))  
    tables=[x for x in filt if x.findAll('table')]
    #print(tables)
    #filt=list(dropwhile(lambda t: 'div' not in t.name,tag_list))   
    #filt = [x for x in filt if x.find('table') is not None]
 
    table=[ x for x in [x.find('table') for x in tables] if x.has_attr('class')][0]
    #tables = [x for x in filt if not 'A user suggests' in x.text]
    #print(table)
    table.find_all('trs',{})
    table_body = table.find('tbody')

    rows = table_body.find_all('tr')

    verbs=[]
    for row in rows:
        cols = row.find_all('td')
        
        if len(cols) == 4:
            v=[]
            for col in cols:
                #print(col.text)
                v.append(col.text.strip())
            verbs.append(v)
    
    #for verb in verbs[0:3]:
    #    print(verb[0:2])
    return verbs
line_parbox='''\\parbox[t][][t]{{2cm}}{{{ich}\\\\{du}\\\\{er}\\\\{wir}\\\\{ihr}\\\\{sie}}}'''
table_verb='''%==={word}===
\\card{{\Huge {word}}}{{
\\begin{{tabular}}{{lll}}
\\parbox[t][][t]{{1.5cm}}{{\\raggedleft ich\\\\du\\\\er/sie/es\\\\wir\\\\ihr\\\\sie}} & 
{present} &
{past}\\\\
\\end{{tabular}}
}}'''

def main():
    try:
        #shuffle(verb_list)
        cards={}
        for verb in verb_list:
            soup=get_result_set(verb)   
            container = soup.find('span',{'id':"German",'class':"mw-headline"})
            if container:
                parent=container.parent
                meaning=get_meaning(parent)
                meaning=[x.split("\n") for x in meaning]
                #meaning=meaning.split('\n')
                print(meaning)
                verblist=get_conjugation(parent)
                
                present=list(itertools.chain.from_iterable([x[0:2] for x in verblist][0:3]))
                past=list(itertools.chain.from_iterable([x[0:2] for x in verblist][3:6]))
                
                out={}
                l=[x.split(" ",1) for x in present]
                l=list(itertools.chain.from_iterable(l))
                l=dict(itertools.zip_longest(*[iter(l)] * 2, fillvalue=""))
                preset_line=line_parbox.format(**l)
                out['present']=preset_line
                
                l=[x.split(" ",1) for x in past]
                l=list(itertools.chain.from_iterable(l))
                l=dict(itertools.zip_longest(*[iter(l)] * 2, fillvalue=""))
                past_line=line_parbox.format(**l)
                out['past']=past_line
                out['word']=verb
                cards[verb]=table_verb.format(**out)
                #print(l)
                #print(table_verb.format(**l))
                

    except Exception as e:
        print('Error on line {}'.format(sys.exc_info()[-1].tb_lineno), type(e).__name__, e)    

    for k, v in cards.items():
        print(v)

if __name__ == "__main__":
    main()