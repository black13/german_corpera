from bs4 import BeautifulSoup
import sys
import re
from random import shuffle 
import itertools
import requests
from itertools import groupby
from itertools import dropwhile,takewhile
from textwrap import wrap
import ftfy
import urllib3
from verblist import verb_list
import string 
def group2(iterator, count):
    return list(itertools.imap(None, *([ iter(iterator) ] * count)))

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

def main():
    
    urllib3.disable_warnings()
    #shuffle(verb_list)
    cards={}
    for verb in verb_list:
        try:
            print(verb)
            soup=get_result_set(verb)  
            soup.encode("utf-8") 
            container = soup.find('span',{'id':"German",'class':"mw-headline"})
            if container:
                out={}
                parent=container.parent
                meaning=get_meaning(parent)
                #text=re.sub(f'[^{re.escape(string.printable)}]', '','\n'.join(meaning))
                text=re.sub(r'[&_{}]*','','\n'.join(meaning))
                out['examples']=wrap(text,50)
                #meaning=meaning.split('\n')
                #print(meaning)
                verblist=get_conjugation(parent)
                
                present=list(itertools.chain.from_iterable([x[0:2] for x in verblist][0:3]))
                past=list(itertools.chain.from_iterable([x[0:2] for x in verblist][3:6]))
                
                
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
                #print(table_verb.format(**out))
        except Exception as e:
            print('Error on line {}'.format(sys.exc_info()[-1].tb_lineno), type(e).__name__, e)    

    f=open("out.tex","w",encoding='utf-8')
    f.write(header)
    for k, v in cards.items():
        f.write(ftfy.fix_text(v))
    f.write(footer)
    f.close()
    

if __name__ == "__main__":
    main()
