import math
from threading import Thread, RLock
from multiprocessing import Process, Lock, freeze_support, Manager
from multiprocessing.managers import DictProxy
from typing import Type
from xml.etree.ElementTree import tostring

from util import Util
from crawling import Crawling

from random import uniform
import time 
import datetime

class Vertex:
    def __init__(self, type, name):
        self.type = type#0: mention, 1:concept
        self.name = name#위키페이지 타이틀명
        self.PR0 = 0
        self.PR = [1,1]
        self.edges = []
        self.pointTo = []
        self.newestPRIdx = 0

class Edge:
    def __init__(self, type):
        self.P = -1#전이확률, 가중치 역할
        self.SR = -1#컨셉간의 간선에만 사용
        self.type = type#mention to concept(0) or concept to concept(1)
        #print("type = %d"%(self.type))

    @classmethod
    def conceptToConcept(cls,SR):#컨셉에서 컨셉으로 가는 간선의 생성자 역할
        temp = Edge(1)
        temp.SR = SR
        return temp

        
    def calcMtoC(self,mentionBacklinkSet:set,conceptBackinkSet:set):
        a=len(mentionBacklinkSet)
        c=len(mentionBacklinkSet & conceptBackinkSet)
        self.P = c/a

class Graph:
    def __init__(self, candidateMention):#candidateMention: 멘션 후보
        self.mentionList = candidateMention#디버그용
        
        self.craw = Crawling()
        self.LOCK_BACKLINKS = Lock()
        self.LOCK_HAVECOUNT = Lock()
        #---------------------------------------------------
        self.MAXENTROPHY = 1000.0
        #---------------------------------------------------

        #candidateMention가 리스트?
        #인정된 맨션들 (1차원 리스트)
        self.mentions, self.conceptsOfMentions = self.getMentionsAndConcepts(candidateMention)
#-------------------------------------------------------------------------------------------------------------------------------------------------------
    #allBacklinksNum = A로 인해 발생한 concept후보들 각각의 전체 백링크 수
    #asAnchortextNum = 위의 백링크들 중에서 앵커텍스트가 A인 링크개수
    def calcEntrophy(self, allBacklinksNum, asAnchortextNum):#mention A 에 대한 entrophy를 구한다
        length = len(allBacklinksNum)#길이는 같은걸로 간주한다
        sum=0
        den = 0
        for i in asAnchortextNum:
            den+=i
        for i in range(length):
            if(asAnchortextNum[i] == 0 or allBacklinksNum[i] == 0 or den == 0):#둘 중 하나라도 0이면 넘김
                continue
            #temp = asAnchortextNum[i]/allBacklinksNum[i]
            temp = asAnchortextNum[i]/den
            sum -= temp * math.log10(temp)
        return sum

    def unproxy_dict(self, dict_proxy):
        return {k: (dict(v) if isinstance(v, DictProxy) else v)
            for k, v in dict_proxy.items()}

    def PROCESS_ANCHORTEXTS(self, cMention, backlinkss_one, out, LOCK_ANCHORTEXTS):#컨셉텍스트, 백링크들, 갯수누적 정수, 락
        for backlink in backlinkss_one:
            while True:
                texts = self.craw.getTexts(backlink)
                if texts != -1:
                    break
                print(datetime.datetime.now())
                print("ERROR(AUTO RETRY), MC_Graph.py, THREAD_ANCHORTEXTS, getTexts, LINE:79, INPUT:" + backlink + '\n')
                time.sleep(uniform(2.0, 10.5))
            try:
                if cMention in texts:
                    LOCK_ANCHORTEXTS.acquire()
                    out[0] += 1
                    LOCK_ANCHORTEXTS.release()
            except TypeError as e:
                print(e)
        return

    def PROCESS_BACKLINKS(self, cMention, cConceptss_one, outs1:dict, outs2:dict):#멘션 메세지, 컨셉후보들, 백링크사이즈들, 엥커텍스트가 포함된 백링크갯수들
        for cConcept in cConceptss_one:
            #print("Thread Backlinks : " + cConcept)#디버그용
            backlinks = self.craw.getBacklinks(cConcept)
            self.LOCK_BACKLINKS.acquire()#임계구역 락
            outs1[cConcept] = len(backlinks)
            self.LOCK_BACKLINKS.release()
            #이후엔 또 작업이 쪼개짐    
            backlinkss = Util.splitList(backlinks, 5)
            threads = []
            havecount = Manager().list()#얕은복사를 위함
            havecount.append(0)
            LOCK_ANCHORTEXTS = Lock()
            for backlinkss_one in backlinkss:
                th = Process(target=self.PROCESS_ANCHORTEXTS, args=(cMention, backlinkss_one, havecount, LOCK_ANCHORTEXTS))
                th.daemon = True
                th.start()
                threads.append(th)
            for th in threads:
                th.join()
            self.LOCK_HAVECOUNT.acquire()#임계구역 락#임계구역 락, 개별로 만드는게 좋겠지만 역시 불안하다.
            outs2[cConcept] = havecount[0]
            self.LOCK_HAVECOUNT.release()
        return

    def getMentionsAndConcepts(self, candidateMentions):
        mentions = []
        conceptsOfMentions = []
        for candidateMention in candidateMentions:
            cheack = self.craw.fc.getCache(4, candidateMention)
            #이미 구했던거라면
            if cheack != -1:
                print(cheack[0])#!!
                if float(cheack[0]) < self.MAXENTROPHY:
                    print(candidateMention)#!!
                    mentions.append(candidateMention)
                    conceptsOfMentions.append(cheack[1:])
                else:
                    print("맨션 탈락")
            #아니라면
            else:
                #----------------------------------------------------------------------------
                while True:
                    candidateConcepts = list(self.craw.getLinks(candidateMention))
                    # t_candidateConcepts = []
                    # for candidateConcept in candidateConcepts:
                    #     texts = self.craw.getTexts(candidateConcept)
                    #     for text in texts:
                    #         if candidateMention in text:
                    #             t_candidateConcepts.append(candidateConcept)
                    #             break
                    if candidateConcepts != -1:
                        break
                    print(datetime.datetime.now())
                    print("ERROR(AUTO RETRY), MC_Graph.py, getMentionsAndConcepts, getLinks, LINE:120, INPUT:" + candidateMention + '\n')
                    time.sleep(time.uniform(0.5, 1.0))
                candidateConceptss = Util.splitList(candidateConcepts, 4)#x개로 쪼개짐
                threads = []
                threadsReturnBacklinksSize = Manager().dict()
                threadsReturnBacklinksHaveText = Manager().dict()
                for candidateConceptss_one in candidateConceptss:
                    th = Process(target=self.PROCESS_BACKLINKS, args=(candidateMention, candidateConceptss_one, threadsReturnBacklinksSize, threadsReturnBacklinksHaveText, ))
                    #th.daemon = True
                    th.start()
                    threads.append(th)
                for th in threads:
                    th.join()
                threadsReturnBacklinksSize = self.unproxy_dict(threadsReturnBacklinksSize)
                threadsReturnBacklinksHaveText = self.unproxy_dict(threadsReturnBacklinksHaveText)
                #----------------------------------------------------------------------------
                allBacklinksNum = []
                asAnchortextNum = []
                candidateConcept_AND_asAnchortextNum = []
                for candidateConcept in candidateConcepts:
                    allBacklinksNum.append(threadsReturnBacklinksSize[candidateConcept])
                    asAnchortextNum.append(threadsReturnBacklinksHaveText[candidateConcept])
                    candidateConcept_AND_asAnchortextNum.append((candidateConcept, threadsReturnBacklinksHaveText[candidateConcept]))
                #----------------------------------------------------------------------------
                nowEntrophy = self.calcEntrophy(allBacklinksNum,asAnchortextNum)
                print(nowEntrophy)#!!
                #맨션이라면-------------------------------------------------------------------
                if nowEntrophy < self.MAXENTROPHY:
                    mentions.append(candidateMention)
                    print(candidateMention)#!!
                    candidateConcept_AND_asAnchortextNum = sorted(candidateConcept_AND_asAnchortextNum, key=lambda x : -x[1])
                    concepts = []
                    for i in range(20):
                        if candidateConcept_AND_asAnchortextNum[i][1] < 2 or len(candidateConcept_AND_asAnchortextNum) == i:
                            break
                        concepts.append(candidateConcept_AND_asAnchortextNum[i][0])

                    self.craw.fc.setToFile(4, candidateMention, ([str(nowEntrophy)]+concepts))#save
                    conceptsOfMentions.append(concepts)
                #----------------------------------------------------------------------------
                else:
                    print("맨션 탈락")
        return mentions, conceptsOfMentions

#-------------------------------------------------------------------------------------------------------------------------------------------------------

    def getAnnotation(self, numberOfAnnotation:int):#text는 mention들의 리스트, numberOfAnnotation는 결과 단어 몇개 출력할지 정하는 변수
        #crl = Crawling()

        li = self.mentions

        self.mentionVertex=[]#멘션 노드 저장장소
        self.mentionSets = set()#비교 연산을 위한 집합
        self.conceptVertex=[]#컨셉 노드 저장장소

        #각 멘션들로 그래프 만들기 시작
        for i in range(len(li)):
            #멘션이 이미 나온 단어인지 아닌지 확인
            if(len(self.mentionSets & set(li[i])) > 0):#같은 단어 이미 만들었으면 넘긴다
                continue
            
            nowMention = Vertex(0,li[i])#멘션 노드 하나 만듬
            self.mentionSets.add(li[i])
            self.mentionVertex.append(nowMention)

            for j in self.conceptsOfMentions[i]:#하나의 멘션에 대한 컨셉들 수만큼 노드, 간선 만듬
                #이미 만든 컨셉 노드중에 같은 노드가 존재하는 지 확인해야함
                index = self.compareConcepts(j)
                if(index == -1):#컨셉 노드 없으면 새로만듬
                    nowConcept = Vertex(1,j)
                    self.conceptVertex.append(nowConcept)
                else:
                    nowConcept = self.conceptVertex[index]

                edge = Edge(0)#mention to concept 엣지 생성
                edge.calcMtoC(self.craw.getBacklinks(li[i]),self.craw.getBacklinks(j))#P(가중치) 계산
                #컨셉노드와 엣지 연결
                edge.dest = nowConcept
                edge.start = nowMention

                nowMention.edges.append(edge)#멘션노드와 엣지 연결
                nowConcept.pointTo.append(edge)#컨셉노드에 자신을가리키는 엣지 리스트에 추가
            #하나의 멘션에대한 컨셉노드 연결 끝
        #모든 멘션에대한 노드 만들기 끝       
            
        #컨셉노드끼리의 간선 이어야함
        for i in range(0,len(self.conceptVertex)):#모든 간선을 돌리면 a노드가 b노드를 가리키고 b노드도 a노드를 가리키는 경우 발생, 
            for j in range(i,len(self.conceptVertex)):#range안에 0을 i로 바꾸면 위에서 말한 이중간선은 없어질듯
                if(i == j):#자기자신을 가리키는 간선 안생김
                    continue
                #i 에서 j로 가는 간선만듬
                N = len(self.conceptVertex)
                SR = self.calcSR(self.craw.getBacklinks(self.conceptVertex[i].name),self.craw.getBacklinks(self.conceptVertex[j].name),N)

                if(SR > 0):#SR값이 0보다커야 간선 추가함
                    edge = Edge.conceptToConcept(SR)
                    edge.dest = self.conceptVertex[j]
                    edge.start = self.conceptVertex[i]
                    oppositeEdge = Edge.conceptToConcept(SR)
                    oppositeEdge.dest = self.conceptVertex[i]
                    oppositeEdge.start = self.conceptVertex[j]

                    self.conceptVertex[i].edges.append(edge)
                    self.conceptVertex[i].pointTo.append(oppositeEdge)
                    self.conceptVertex[j].edges.append(oppositeEdge)
                    self.conceptVertex[j].pointTo.append(edge)
        
        #모든 노드와 간선 생성완료

        #PR0 계산
        sum = 0
        for i in self.mentionVertex:#z를 제외한 계산 완료
            i.PR0 = len(self.craw.getBacklinks(i.name))/self.craw.getPR0den(i.name)#Crawling에 만들어놓은거 그대로 사용
            sum +=i.PR0
        z = 1/sum
        for i in self.mentionVertex:#z를 곱해줘서 계산 완료
            i.PR0 *= z

        #P(c,c')계산
        for i in self.conceptVertex:
            sum = 0
            for j in i.edges:
                sum += j.SR

            for j in i.edges:
                if sum-j.SR == 0:#컨셉 노드가 적은경우 0인 경우가 발생
                    j.P = 1#임시로 1로 지정하도록 변경
                else:
                    j.P = j.SR/(sum-j.SR)

        #PR계산
        self.calcPR(10)
        supportNodeList = self.calcSupportConcept()
        
        return supportNodeList[:numberOfAnnotation]
    def compareConcepts(self, candidateConcept:str):#노드 이미있으면 해당하는 인덱스 출력 없으면 -1
        index = 0
        for i in self.conceptVertex:
            if(i.name == candidateConcept):
                return index
            index+=1
        return -1
    def calcSR(self, start_set:set, end_set:set, N):
            
        sameNum = len(start_set & end_set)
            
        #집합 사이즈 저장
        startLen = len(start_set)
        endLen = len(end_set)

        #수식 계산
        SR = 0
        if sameNum == 0:#log10에 0이 들어가면 에러뜸
            return 0
        denominator = (math.log10(N) - math.log10(min(startLen,endLen)))
        numerator = (math.log10(max(startLen,endLen)) - math.log10(sameNum)) #분자
        if(denominator == 0):#분모가 0인 경우가 발생할 수 있음. 임시로 0으로 처리하는걸로 해놓음
            SR = 0
        else:
            SR = 1- numerator / denominator
        
        return SR 

    def calcPR(self, repeat:int):
        #repeat:반복계산 횟수
        allVertex = self.mentionVertex + self.conceptVertex
        r =0.1
        for i in range(repeat):
            print("repeat num: %d" %(i+1))
            self.newIdx = i%2
            self.oldIdx = (i+1)%2
            for vertex in allVertex:
                sum=0
                vertex.newestPRIdx = self.newIdx
                for edge in vertex.pointTo:
                    sum += edge.start.PR[self.oldIdx] * edge.P
                vertex.PR[self.newIdx] = r *vertex.PR0  + (1-r)*sum
                print("name: "+ vertex.name + " PR: %lf"%( vertex.PR[self.newIdx]))
        return
    def calcSupportConcept(self):
        #멘션당 PR값이 가장 높은 하나의 노드를 제외하고 나머지 노드를 없앤다
        supportNode = set()
        for mNode in self.mentionVertex:
            maxPR = -1
            maxNode = -1
            for i in range(len(mNode.edges)):
                if maxPR < mNode.edges[i].dest.PR[self.newIdx]:
                    maxPR = mNode.edges[i].dest.PR[self.newIdx]
                    maxNode = i
            #멘션노드가 아무노드와 연결되어있지 않는경우 에러 발생
            temp = mNode.edges[maxNode]
            mNode.edges[maxNode] = mNode.edges[0]
            mNode.edges[0]=temp
            if not(temp.dest in supportNode):
                supportNode.add(temp.dest)
            
            '''
            #나머지 엣지들 제거
            for i in mNode.edges:
                if i == mNode.edges[0]:
                    continue
                i.dest.pointTo.remove(i)
                mNode.edges.remove(i)
            #제거 완료

        #컨셉노드 중 자신을 가리키는 노드가 없는경우 삭제
        for cNode in self.conceptVertex:
            if len(cNode.pointTo) == 0:
                self.conceptVertex.remove(cNode)#이렇게 둘다 삭제해야 하나?
                del cNode
        
            '''
        supportNode = list(supportNode)
        supportNode = sorted(supportNode, key = lambda node: node.PR, reverse=True)
        return supportNode

if __name__ == '__main__':
    freeze_support()
    #ans = Graph(['testing', 'cat', 'rainbow']).getAnnotation(5)
    print("start program")
    timeStart = time.time()
    g = Graph(['cat','dog'])
    result = g.getAnnotation(5)
    print("\n")
    for i in range(len(result)):
        print("node: "+result[i].name)
        print("PR: %lf"%(result[i].PR[g.newIdx]))
        print("")
    timeEnd = time.time()
    sec = timeEnd - timeStart
    result_list = str(datetime.timedelta(seconds=sec))
    print(result_list)