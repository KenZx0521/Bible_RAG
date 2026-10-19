"""Regnal-formula regexes of the regnal layer (K-regnal), ported from experiment A's layer_re.py
(probe_C5 auto_layer.py); fixed 2026-10-19: the patterns of rules R1b, R2, R3, R4, R5 and R10
and the united-monarchy kingdom of R8 (``regnal_formulas``). Changing one changes the layer and
G-REGNAL's pinned sha256."""
import re

C = '[一-鿿‧]'
N1 = C + '{2,4}?'
NUM = '[一二三四五六七八九十百零兩]+'
FOREIGN_DEATH = re.compile('(亞蘭|亞述|摩押|巴比倫|埃及|以東|推羅)王' + C + '{1,6}?死了')

P_ACC1 = re.compile(r'(?P<rk>猶大王|以色列王)?(?:(?P<rf>' + N1 + r')的兒子)?(?P<rn>' + N1 + r')(?:王)?第?(?P<y>' + NUM +
                    r')年[，,](?:[^，。]{0,14}[，,])?(?P<nk>猶大王|以色列王)?(?:(?P<nf>' + N1 + r')的兒子)?(?P<nn>' + N1 +
                    r')(?:在(?P<cap>' + C + r'{2,4}?))?(?P<tail>登基|作(?:了)?(?:以色列|猶大)?(?:眾人的)?王)')
P_ACC_REV = re.compile(r'(?P<nn>' + N1 + r')登基作(?P<nk>猶大|以色列)王的時候，是在(?:(?P<rf>' + N1 + r')的兒子)?(?P<rn>' + N1 + r')第?(?P<y>' + NUM + r')年')
P_ACC_SUCC_SYNC = re.compile(r'接續他作王，正在(?P<rk>猶大王|以色列王)?(?:(?P<rf>' + N1 + r')的兒子)?(?P<rn>' + N1 + r')第?(?P<y>' + NUM + r')年')
P_COUP_SYNC = re.compile(r'(?:(?P<rf>' + N1 + r')的兒子)?(?P<rn>' + N1 + r')第?(?P<y>' + NUM + r')年[，,](?:(?P<nf>' + N1 + r')的兒子)?(?P<nn>' + N1 + r')背叛')
P_ACC0 = re.compile(r'(?P<pre>' + C + r'{2,8})作(?P<nk>猶大|以色列)王[。，].{0,3}登基的時候')
P_AGE = re.compile(r'(?P<pre>' + C + r'{0,6}?)登基的時候(?:年)?(?:方)?(?P<a>' + NUM + r')歲')
P_AGE2 = re.compile(r'那時他年(?P<a>' + NUM + r')歲')
P_REIGN = re.compile(r'(?P<pre>' + C + r'{0,10}?)作(?:了)?(?P<k>猶大|以色列(?:眾人的)?|以色列和猶大)?王(?:共)?(?P<v>' + NUM + r')(?P<u>年|個月|日)')
P_MOTHER = re.compile(r'母親名叫(?P<m>' + C + r'{1,5}?)(?:[，,。；]|$)(?:(?:是|乃)(?P<d>[^。；]{1,14}?)[。；])?')
P_SUCC = re.compile(r'(?:兒子|兄弟)(?P<s>' + N1 + r')(?:在' + C + r'{2,5}?)?接續(?:他父親(?P<pf>' + C + r'{2,4})?|他父|他)作王')
P_SEAT = re.compile(r'(?P<s>' + N1 + r')坐了他的位')
P_REPL = re.compile(r'立(?:' + N1 + r'的叔叔)?(?P<s>' + N1 + r')代替他作王')
P_SLEEP = re.compile(r'(?P<n>' + N1 + r')與(?:他)?列祖(?:以色列諸王)?(?:一同)?同睡')
P_USURP = re.compile(r'篡了(?:他的位|國位)')
P_VERB = re.compile(r'背叛|殺了|擊殺|就進去|篡了')
P_RENAME = re.compile(r'改名叫(?P<new>' + N1 + r')[，,。]')
P_FN_ALIAS = re.compile(r'^(又名|就是)(' + C + r'{2,5})$')
# R2: the death formula with a pronoun subject, after the verse's reign formula (1ki.14.20)
P_SLEEP_PRON = re.compile(r'(?:，就|而死，)與(?:他)?列祖(?:以色列諸王)?(?:一同)?同睡')
# R1b: a span right before the usurpation clause is the usurper's reign (2ki.11.3)
P_USURP_SPAN = re.compile(r'(?P<v>' + NUM + r')(?P<u>年|個月|日)[；;，,](?P<n>' + N1 + r')篡了(?:他的位|國位)')
# R3: the people make a named man king (1ki.16.16); the name is the lexicon suffix of pre
P_PEOPLE = re.compile(r'(?:民|眾人)[^，。；]{0,8}?立(?P<pre>' + C + r'{2,6}?)作(?P<k>以色列|猶大)王')
# R4: a named man rebels against a named king (2ki.9.14); both names are checked against the lexicons
P_REBEL = re.compile(r'(?:(?P<uf>' + N1 + r')的兒子)?(?P<u>' + N1 + r')背叛(?:' + N1 + r'的兒子)?(?P<v>' + N1 +
                     r')(?=[，,。；、]|$)')
# R5: anointing a prince named by a pronoun (2ki.11.12); 立他作王 stays out, it also makes a rival (1ki.16.21)
P_ANOINT = re.compile(r'膏(?:了)?他作王')
# R10: a bare 作王N年 (no 共, 在, 登基 or kingdom) is a length only where the sentence ends or the king dies
P_REIGN_END = re.compile(r'[。；]|，就與|而死|$')

OPP = {'J': 'I', 'I': 'J'}
KMAP = {'猶大王': 'J', '以色列王': 'I', '猶大': 'J', '以色列': 'I'}
CHAIN_KINGDOMS = ('I', 'J')
UNITED = 'U'   # R8: the united monarchy (a king of all Israel), on neither chain


def zh2int(s):
    d = {'零': 0, '一': 1, '二': 2, '兩': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    total, cur = 0, 0
    for ch in s:
        if ch in d:
            cur = d[ch]
        elif ch == '十':
            total += (cur or 1) * 10
            cur = 0
        elif ch == '百':
            total += (cur or 1) * 100
            cur = 0
    return total + cur
