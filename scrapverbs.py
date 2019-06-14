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

def get_result_set(verb):
    url="http://en.wiktionary.org/wiki/{0}#Conjugation".format(verb)
    res = requests.get(url,verify=False)
    soup = BeautifulSoup(res.text,"html.parser")
    return soup

def recursiveChildren(x):
    if "childGenerator" in dir(x):
        for child in x.childGenerator():
            name = getattr(child, "name", None)
            if name is not None:
                print ("[Container Node]",child.name)
            recursiveChildren(child)
    else:
        if not x.isspace(): #Just to avoid printing "\n" parsed from document.
            print ("[Terminal Node]",x)
            

def get_meaning(parent):
    tag_list = [x for x in parent.find_next_siblings()]
    filt=list(takewhile(lambda t: 'Conjugation[edit]' not in t.text,tag_list))
    filt=list(dropwhile(lambda t: 'Verb[edit]' not in t.text,filt))
    
    ol = [x for x in [x for x in filt if x.name == 'ol']]
    text = [ftfy.fix_text(x.text) for x in ol[0].find_all(recursive=False)]
    #print (text)
    #text=[ftfy.fix_text(x.text) for x in list(itertools.chain.from_iterable([x.findAll('li') for x in filt]))]
    #text=[x.text for x in list(itertools.chain.from_iterable([x.findAll('span',{'class':'gloss-content'}) for x in filt]))]
    #examples=[x.text for x in list(itertools.chain.from_iterable([x.findAll('div',{'class':'h-usage-example'}) for x in filt]))]
    #text = text + examples
    return text


def get_conjugation(parent):
    tag_list = [x for x in parent.find_next_siblings()]
    filt=list(dropwhile(lambda t: 'Conjugation[edit]' not in t.text,tag_list))  
    tables=[x for x in filt if x.findAll('table')]

    table=[ x for x in [x.find('table') for x in tables] if x.has_attr('class')][0]

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
    
    return verbs


line_parbox='''\\parbox[t][][t]{{2cm}}{{\\normalfont {ich}\\\\{du}\\\\{er}\\\\{wir}\\\\{ihr}\\\\{sie}}}'''
table_verb='''
%==={word}===
\\card{{\\normalfont \\Huge {word}}}{{
\\begin{{tabular}}{{lll}}
\\parbox[t][][t]{{2.0 cm}}{{\\normalfont \\raggedleft ich\\\\du\\\\er/sie/es\\\\wir\\\\ihr\\\\sie}} &    
{present} &
{past}\\\\
\\end{{tabular}}
\\begin{{tabular}}{{l}}
\\parbox[t][][t]{{8cm}}{{}}\\\\
\\parbox[t][][t]{{8cm}}{{\\normalfont \\small {examples} }}\\\\
\\end{{tabular}}
}}'''

header='''\\documentclass[a4paper,backgrid,frontgrid]{flacards}
\\usepackage{array,booktabs,tabularx}
\\usepackage[condensed,sfdefault]{universalis}
\\usepackage[T1]{fontenc}
\\begin{document}
\\pagesetup{2}{4}
'''

footer='''\\end{document}'''

explaination_parbox='''\\parbox[t][][t]{{8cm}}{{{text}}}'''

def parse(verb):
    verblist=[]
    out={}
    latex=""
    headers = {
        'user-agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_11_6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/53.0.2785.143 Safari/537.36'}
    try:
        url="http://en.wiktionary.org/wiki/{0}#Conjugation".format(verb)   
    
        r = requests.get(url, headers=headers,verify=False, timeout=10)
        sleep(2)
        
        if r.status_code == 200:
            print('Processing..' + url)
            html = r.text
            soup = BeautifulSoup(html, "html.parser")
            tables=soup.select('table[class="inflection-table"]')
            
            table=None
            for t in tables:
                tl=[x for x in t.text.split("\n") if len(x) > 0]
                if 'infinitive' in tl and 'present participle' in tl and 'past participle' in tl:
                    table=t
                    break
            if table is not None:
                rows = table.find_all('tr')
                for row in rows:
                    cols = row.find_all('td')    
                    if len(cols) == 4:
                        v=[]
                        for col in cols: 
                        #print(col.text)
                            v.append(col.text.strip())
                        verblist.append(v)
            
            present=list(chain.from_iterable([x[0:2] for x in verblist][0:3]))
            past=list(chain.from_iterable([x[0:2] for x in verblist][3:6]))
                
            out['examples']=""    
            l=[x.split(" ",1) for x in present]
            l=list(chain.from_iterable(l))
            l=dict(zip_longest(*[iter(l)] * 2, fillvalue=""))
            preset_line=line_parbox.format(**l)
            out['present']=preset_line
                
            l=[x.split(" ",1) for x in past]
            l=list(chain.from_iterable(l))
            l=dict(zip_longest(*[iter(l)] * 2, fillvalue=""))
            past_line=line_parbox.format(**l)
            out['past']=past_line
            out['word']=verb
            latex=table_verb.format(**out)
    except Exception as e:
        print('Error on line {}'.format(sys.exc_info()[-1].tb_lineno), type(e).__name__, e)
    return latex

def main():
    #use with thread pools
    urllib3.disable_warnings()
    #shuffle(verb_list)
    p = Pool(20)  # Pool tells how many at a time
    records = p.map(parse, verb_list)

    p.terminate()
    p.join()
    

    f=open("verbs.tex","w",encoding='utf-8')
    f.write(header)
    for record in records:
        f.write (record)
    f.write(footer)
    f.close()

if __name__ == "__main__":
    main()
