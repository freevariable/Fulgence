#!/usr/bin/python
#Copyright 2018 freevariable (https://github.com/freevariable)

#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at

#      http://www.apache.org/licenses/LICENSE-2.0

#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import redis,random,math,sys,uuid
import time,datetime,getopt,flask,json
from concurrent.futures import ThreadPoolExecutor
import cPickle as pickle

redisDB=0
live=[]
schedOrders=[]
saveOrder={}
version="148"
minVersion="146"
hasTime=False
hasServices=False
startTime=datetime.datetime.strptime("001d06h30m00s","%jd%Hh%Mm%Ss")
SAVEFREQ=7200  # Save sim to saves/ dir every SAVEFREQ seconds
CLOCKHEADWAY=35  # in secs
ADHESIVEFACTOR=0.25
G=9.81  # N/kg
MULTICORE=False
CORES=1
WHEELFACTOR=G*0.025
DUMPDATA=True
TPROGRESS=False
STAPROGRESS=True
ACCSIGMA=0.0027
ACC=1.35 # m/s2  au demarrage
ALAW='EMU1'   # law governing acc
              # EMU1 is for MP05 EMUs
              # STM1 is for steam engines
WEIGHT=143000.0   #in kg
PAXWEIGHT=75.0   #in kg
MAXPAX=698
UNITS='metric'
MPH=1.60934  #mph to kmh
POWER=2000000.0 #in W
VMX=80.0   #km/h  max speed
VMX2=(VMX*VMX)/12.96  # VMX squared, in m/s
AIRFACTOR=0.368888/VMX2
TLENGTH=90.0  #length in m
DCC=-1.10  #m/s2
EMR=-1.50   #m/s2 emergency dcc
DLAW='EMU1'    # law governing dcc between t=0 and t=tpoint
          # EMU1 is  for MP05 EMUs
SYNCPERIOD=0.5 # how often (in s) do we sync multicores
CYCLEPP=100    # how many ticks we calculate between two multicore syncs
CYCLE=CYCLEPP/SYNCPERIOD # how many ticks we calculate per second 
             # increasing cycle beyond 200 does not improve precision by more that 1 sec for the end-to-end journey
T0=0.0
VTHRESH=0.999
CONTROL="SIG"    # two mutually exclusive values: SIG or TVM
REALTIME=False
SIGPOLL=1.0   # check for sig clearance (in sec)

tivs={}
stas={}
srvs={}
sigs={}
trss={}
conf={}
trs=[]
remlist=[]
segs={}
ncyc=0
t=0.0
maxLine=160.0    # max speed allowed on a line, km/h
exitCondition=False
projectDir='/'
schedulesDir='schedules/'
segmentsDir='segments/'

def initConfig():
  f=open(projectDir+"routeConfig.txt","r")
  ssf=f.readlines()
  ss=[]
  f.close()
  cnt=0
  for s in ssf:
    if (s[0]!='#'):
      s=s.rstrip().split(" ")
      ss.append(s)
      cnt=cnt+1  
  return ss

def initSRVs():
  f=open(projectDir+"services.txt","r")
  ssf=f.readlines()
  ss=[]
  f.close()
  cnt=0
  for s in ssf:
    if (s[0]!='#'):
      s=s.rstrip().split(" ")
      ss.append(s)
      cnt=cnt+1  
  return ss

def initSEGs():
  f=open(projectDir+"segments.txt","r")
  ssf=f.readlines()
  ss=[]
  f.close()
  cnt=0
  for s in ssf:
    if (s[0]!='#'):
      s=s.rstrip()
      ss.append(s)
      cnt=cnt+1  
  return ss

def initTIVs():
  global segs
  global conf
  gts={}
  for se in segs:
    f=open(projectDir+segmentsDir+se+"/TIVs.txt","r")
    tsf=f.readlines()
    ts=[]
    f.close()
    cnt=0
    for t in tsf:
      if (t[0]!='#'):
        t=t.rstrip().split(" ")
        if conf['units']=='imperial':
          t[0]=str(float(t[0])*MPH)  #mileposts=>pK
          t[1]=str(float(t[1])*MPH)  #mph=>kmh
        ts.append(t)
        cnt=cnt+1  
    gts[se]=ts
  return gts

def initStock():
    f=open(projectDir+stockName,"r")
    tsf=f.readlines()
    ts=[]
    f.close()
    cnt=0
    for t in tsf:
      if (t[0]!='#'):
        t=t.rstrip().split(" ")
        ts.append(t)
        cnt=cnt+1  
    return ts

def initSchedule():
    global hasTime
    global startTime
    f=open(projectDir+schedulesDir+scheduleName,"r")
    tsf=f.readlines()
    ts=[]
    f.close()
    for t in tsf:
      if (t[0]!='#'):
        t=t.rstrip().split(" ")
        if t[0]=='Time':
          hasTime=True
          auxT="001d"+t[1]
          startTime=datetime.datetime.strptime(auxT,"%jd%Hh%Mm%Ss")
        else:
          ts.append(t)
    return ts

def initCRVs():
  global segs
  global conf
  gts={}
  for se in segs:
    f=open(projectDir+segmentsDir+se+"/CRVs.txt","r")
    ssf=f.readlines()
    ss=[]
    f.close()
    cnt=0
    for s in ssf:
      if (s[0]!='#'):
        s=s.rstrip().split(" ")
        if conf['units']=='imperial':
          s[0]=str(float(s[0])*MPH) #miles=>pK
        ss.append(s)
        cnt=cnt+1  
    gts[se]=ss
  return gts

def initGRDs():
  global segs
  global conf
  gts={}
  for se in segs:
    f=open(projectDir+segmentsDir+se+"/GRDs.txt","r")
    ssf=f.readlines()
    ss=[]
    f.close()
    cnt=0
    for s in ssf:
      if (s[0]!='#'):
        s=s.rstrip().split(" ")
        if conf['units']=='imperial':
          s[0]=str(float(s[0])*MPH) #miles=>pK
        ss.append(s)
        cnt=cnt+1  
    gts[se]=ss
  return gts

def initSTAs():
  global segs
  global conf
  gts={}
  for se in segs:
    f=open(projectDir+segmentsDir+se+"/STAs.txt","r")
    ssf=f.readlines()
    ss=[]
    f.close()
    cnt=0
    for s in ssf:
      if (s[0]!='#'):
        s=s.rstrip().split(" ")
        if conf['units']=='imperial':
          s[0]=str(float(s[0])*MPH) #milepost=>pK
        ss.append(s)
        cnt=cnt+1  
    gts[se]=ss
  return gts

def initSIGs():
  global segs
  global conf
  gts={}
  for se in segs:
    f=open(projectDir+segmentsDir+se+"/SIGs.txt","r")
    ssf=f.readlines()
    ss=[]
    f.close()
    cnt=0
    for s in ssf:    # FIRST pass
      redisSIG=""
      if (s[0]!='#'):
        s=s.rstrip().split(" ")
        if conf['units']=='imperial':
          s[0]=str(float(s[0])*MPH) #mile=>pK
        if (len(s)<=2):
          s.append('1')   # this is a type 1 sig by default
          redisSIG="green"
        else:
          if ((s[2]=='1')or (s[2]=='6')):    # type 1 or 6
            redisSIG="green"
          elif (s[2]=='4C'):   #type 4C
            redisSIG="green"
            if (len(s)!=6):
              print "FATAL: type 4C sig requires 6 x verb:noun"
              print s
              print len(s)
              sys.exit()
            verbnoun=s[3].split(":") 
            if verbnoun[0]=="Main":
              if not __debug__:
                print "switch:"+s[1]+" main branch and default set to: "+verbnoun[1]
              r.set("switch:"+s[1]+":mainPosition",verbnoun[1])
              r.set("switch:"+s[1]+":position",verbnoun[1])
              if se==verbnoun[1]:
                redisSIG="green" 
            verbnoun=s[4].split(":") 
            if verbnoun[0]=="Branch":
              if not __debug__:
                print "switch:"+s[1]+" branch set to: "+verbnoun[1]
              r.set("switch:"+s[1]+":branchPosition",verbnoun[1])
              if se==verbnoun[1]:
                redisSIG="red" 
            verbnoun=s[5].split(":") 
            if verbnoun[0]=="BranchOrientation":
              if not __debug__:
                print "switch:"+s[1]+" branch orientation set to: "+verbnoun[1]
              r.set("switch:"+s[1]+":branchOrientation",verbnoun[1])
          elif (s[2]=='4D'):   #type 4D
            redisSIG="green"
            if (len(s)!=6):
              print "FATAL: type 4D sig requires 6 x verb:noun"
              print s
              print len(s)
              sys.exit()
            verbnoun=s[3].split(":") 
            if verbnoun[0]=="Main":
              if not __debug__:
                print "switch:"+s[1]+" main branch and default set to: "+verbnoun[1]
              r.set("switch:"+s[1]+":mainPosition",verbnoun[1])
              r.set("switch:"+s[1]+":position",verbnoun[1])
            verbnoun=s[4].split(":") 
            if verbnoun[0]=="Branch":
              if not __debug__:
                print "switch:"+s[1]+" branch set to: "+verbnoun[1]
              r.set("switch:"+s[1]+":branchPosition",verbnoun[1])
            verbnoun=s[5].split(":") 
            if verbnoun[0]=="BranchOrientation":
              if not __debug__:
                print "switch:"+s[1]+" branch orientation set to: "+verbnoun[1]
              r.set("switch:"+s[1]+":branchOrientation",verbnoun[1])
          elif (s[2]=='2'):   #type 2
            redisSIG="red"
            if (len(s)!=6):
              print "FATAL: type 2 sig requires 3 x verb:noun"
              print s
              print len(s)
              sys.exit()
            verbnoun=s[3].split(":") 
            if verbnoun[0]=="Reverse":
              if not __debug__:
                print "switch:"+s[1]+" reverse set to: "+verbnoun[1]
              r.set("switch:"+s[1]+":reversePosition",verbnoun[1])
            else:
              print "FATAL: unkwnown Verb "+ verbnoun[0]+". Reverse was expected."
              sys.exit()
            verbnoun=s[4].split(":")
            if verbnoun[0]=="Forward":
              if not __debug__:
                print "switch:"+s[1]+" forward set to: "+verbnoun[1]
              r.set("switch:"+s[1]+":forwardPosition",verbnoun[1])
            else:
              print "FATAL: unkwnown Verb "+ verbnoun[0]
              sys.exit()
            verbnoun=s[5].split(":")
            if verbnoun[0]=="Default":
              if not __debug__:
                print "switch:"+s[1]+" current set to: "+verbnoun[1]
              r.set("switch:"+s[1]+":position",verbnoun[1])
            else:
              print "FATAL: unkwnown Verb "+ verbnoun[0]
              sys.exit()
        if (len(redisSIG)>2):
          r.set("sig:"+se+":"+s[1],redisSIG)
        ss.append(s)
        cnt=cnt+1  
    prevs=None
    if not __debug__:
      print "______"+se+"_______"
    cnt=0
    for s in ss:    # SECOND PASS
      aligned=False
      if ((s[2]=='4D') or (s[2]=='4C')):  # type 4 SIG
        k=r.get("switch:"+s[1]+":position")       
        kMain=r.get("switch:"+s[1]+":mainPosition")       
        if not __debug__:
          print "switch of sig "+s[1]+" is in position "+k
        if (k==se):
          if not __debug__:
            print "  switch of sig "+s[1]+" is aligned to segment"
          aligned=True
        if (cnt<len(ss)-1):
          if not __debug__:
            print "  switch of sig "+s[1]+" has a next sig in current seg: "+ss[cnt+1][1]+" of type: "+ss[cnt+1][2]
        if prevs is not None:
          if not __debug__:
            print "  switch of sig "+s[1]+" has a prev sig: "+prevs[1]+" of type: "+prevs[2]
          if (s[2]=='4D'):
            r.set("switch:"+s[1]+":mainPrevSig",cnt-1)
          if (s[2]=='4C'):
            if se==kMain:
              r.set("switch:"+s[1]+":mainPrevSig",cnt-1)
            else:
              r.set("switch:"+s[1]+":branchPrevSig",cnt-1)
          if ((s[2]=='4D') and (prevs[2]!='1')):
            print "FATAL: a sig type 4D must be preceded by a type 1 or no sig!"
            sys.exit()
          if ((s[2]=='4C') and (prevs[2]!='6')):
            print "FATAL: a sig type 4C must be preceded by a type 6!"
            sys.exit()
          k1=r.get("sig:"+se+":"+prevs[1])       
          if k1 is None:
            if (aligned==True):
              r.set("sig:"+se+":"+prevs[1],"green")
            else:
              r.set("sig:"+se+":"+prevs[1],"yellow")
          else:
            if k1=='green':
              if (aligned==False):
                r.set("sig:"+se+":"+prevs[1],"yellow")
          k1=r.get("sig:"+se+":"+prevs[1])       
          if not __debug__:
            print "  prev color set to: "+k1
        else:
          if not __debug__:
            print "  (switch has no prev)"
      if (s[2]=='2'):  # type 2 SIG
        k=r.get("switch:"+s[1]+":position")       
        if not __debug__:
          print "switch of sig "+s[1]+" is in position "+k
        if (k==se):
          if not __debug__:
            print "  switch of sig "+s[1]+" is aligned to segment"
          aligned=True
        if (cnt<len(ss)-1):
          if not __debug__:
            print "  switch of sig "+s[1]+" has a next sig: "+ss[cnt+1][1]+" of type: "+ss[cnt+1][2]
          if (ss[cnt+1][2]!='5'):
            print "FATAL: a sig type 2 must be followed by a type 5!"
            sys.exit()
          k1=r.get("sig:"+se+":"+ss[cnt+1][1])
          if k1 is None:
            if (aligned==True):
              r.set("sig:"+se+":"+ss[cnt+1][1],"green")
            else:
              r.set("sig:"+se+":"+ss[cnt+1][1],"red")
          else:
            if ((k1=="green") or k1==("yellow")):
              if (aligned==False):
                r.set("sig:"+se+":"+ss[cnt+1][1],"red")
          k1=r.get("sig:"+se+":"+ss[cnt+1][1])       
        else:
          if not __debug__:
            print "  (switch has no succ)"
        if prevs is not None:
          if not __debug__:
            print "  switch of sig "+s[1]+" has a prev sig: "+prevs[1]+" of type: "+prevs[2]
            print "   so we set forwardPrevSig to "+str(cnt-1)+" for "+s[1]
          r.set("switch:"+s[1]+":forwardPrevSig",cnt-1)
          if (prevs[2]!='3'):
            print "FATAL: a sig type 2 must be preceded by a type 3 or no sig!"
            sys.exit()
          else:
            k1=r.get("sig:"+se+":"+prevs[1])       
            if k1 is None:
              if (aligned==True):
                r.set("sig:"+se+":"+prevs[1],"yellow")
              else:
                r.set("sig:"+se+":"+prevs[1],"yellow")
            k1=r.get("sig:"+se+":"+prevs[1])       
            if not __debug__:
              print "  prev color set to: "+k1
        else:
          if not __debug__:
            print "  (switch has no prev)"
      else: #not a type 2
        if ((s[2]!='4C') and (cnt==len(ss)-1)): 
          if not __debug__:
            print "INFO: SIG "+str(s)+" has not succ and is neither a type 2 nor a type 4C" 
          r.set("sig:"+se+":"+s[1],"red")
      prevs=s
      cnt=cnt+1
    gts[se]=ss
  return gts

def initAll():
  global tivs
  global stas
  global sigs
  global trss
  global grds
  global crvs
  global trs
  global segs
  global jumpseat
  global r
  global stock
  global conf
  global hasServices
  global srvs
  random.seed()
  stock={}
  r.set('realtime:',REALTIME)
  confraw=initConfig()
  conf['units']='metric'
  for aa in confraw:
    if (aa[0]!="#"):
      if (aa[0]=='units'):
        conf['units']=aa[1]
      if (aa[0]=='speedLine'):
        maxLine=float(aa[1])
  if not __debug__:
    print "routeConfig details:"
    print confraw
    print conf
  segs=initSEGs()
  tivs=initTIVs()
  stas=initSTAs()
  sigs=initSIGs()
  trss=initSchedule()
  grds=initGRDs()
  crvs=initCRVs() 
  stockraw=initStock()
  cnt=0
  stock['acceleration']=ACC
  stock['waitTime']=10.0 # at stations, in secs
  stock['k']=0.25
#  stock['timbre']=18.0
  stock['cylinders']=2
  stock['accelerationLaw']=ALAW
  stock['weight']=WEIGHT   # whole train for EMUs, carriages only for pushed/pulled trains.
  stock['tenderAxleLoad']=0.0  # always 0 for EMUs, in kg, including full water and coal
  stock['driveAxleLoad']=0.0  # always 0 for EMUs, in kg
  stock['deadFrontAxleLoad']=0.0  # always 0 for EMUs, in kg
  stock['deadRearAxleLoad']=0.0  # always 0 for EMUs, in kg
  stock['carriagesWeight']=0.0  # always 0 for EMUs
  stock['waterCapacity']=0.0  # max kg of water in tender
  stock['coalCapacity']=0.0  # max kg of coal in tender
  stock['power']=POWER   # only makes sense for EMUs
  stock['maxSpeed']=VMX
  stock['criticalSpeed']=0.0  # for STM only, in km/h
  stock['airFactor']=AIRFACTOR   # only makes sense for EMUs
  stock['railFactor']=WHEELFACTOR   # only makes sense for EMUs
  stock['length']=TLENGTH
  stock['deceleration']=DCC
  stock['decelerationLaw']=DLAW
  stock['emergency']=EMR
  stock['maxPax']=MAXPAX
  stock['paxWeight']=PAXWEIGHT
  stock['criticalSpeed']=0.0
  for aa in stockraw:
    if (aa[0]!="#"):
      if (aa[0]=='acceleration'):
        stock['acceleration']=float(aa[1])
      if (aa[0]=='expansion'):
        stock['expansion']=aa[1]
      if (aa[0]=='units'):
        stock['units']=aa[1]
      if (aa[0]=='driveAxles'):
        stock['driveAxles']=int(aa[1])
      if (aa[0]=='deadFrontAxles'):
        stock['deadFrontAxles']=int(aa[1])
      if (aa[0]=='deadFrontAxleLoad'):
        stock['deadFrontAxleLoad']=float(aa[1])
      if (aa[0]=='deadRearAxleLoad'):
        stock['deadRearAxleLoad']=float(aa[1])
      if (aa[0]=='driveAxleLoad'):
        stock['driveAxleLoad']=float(aa[1])
      if (aa[0]=='deadRearAxles'):
        stock['deadRearAxles']=int(aa[1])
      if (aa[0]=='tenderAxles'):
        stock['tenderAxles']=int(aa[1])
      if (aa[0]=='cylinders'):
        stock['cylinders']=int(aa[1])
      if (aa[0]=='wheelsDiameter'):
        stock['wheelsDiameter']=float(aa[1])
      if (aa[0]=='frontSurface'):
        stock['frontSurface']=float(aa[1])
      if (aa[0]=='pistonsLength'):
        stock['pistonsLength']=float(aa[1])
      if (aa[0]=='waitTime'):
        stock['waitTime']=float(aa[1])
      if (aa[0]=='indicatedGrade'):
        stock['indicatedGrade']=float(aa[1])
      if (aa[0]=='indicatedCurve'):
        stock['indicatedCurve']=float(aa[1])
      if (aa[0]=='k'):
        stock['k']=float(aa[1])
      if (aa[0]=='timbre'):
        stock['timbre']=float(aa[1])
      if (aa[0]=='accelerationLaw'):
        stock['accelerationLaw']=aa[1]
      if (aa[0]=='weight'):
        stock['weight']=float(aa[1])
      if (aa[0]=='waterCapacity'):
        stock['waterCapacity']=float(aa[1])
      if (aa[0]=='coalCapacity'):
        stock['coalCapacity']=float(aa[1])
      if (aa[0]=='tenderAxleLoad'):
        stock['tenderAxleLoad']=float(aa[1])
      if (aa[0]=='carriagesWeight'):
        stock['carriagesWeight']=float(aa[1])
      if (aa[0]=='power'):
        stock['power']=float(aa[1])
      if (aa[0]=='maxSpeed'):
        stock['maxSpeed']=float(aa[1])
        if conf['units']=='imperial':
          stock['maxSpeed']=float(stock['maxSpeed'])*MPH
      if (aa[0]=='criticalSpeed'):
        stock['criticalSpeed']=float(aa[1])
        if conf['units']=='imperial':
          stock['criticalSpeed']=float(stock['criticalSpeed'])*MPH
      if (aa[0]=='airFactor'):
        stock['airFactor']=float(aa[1])
      if (aa[0]=='length'):
        stock['length']=float(aa[1])
      if (aa[0]=='deceleration'):
        stock['deceleration']=float(aa[1])
      if (aa[0]=='maxPax'):
        stock['maxPax']=int(aa[1])
      if (aa[0]=='paxWeight'):
        stock['paxWeight']=float(aa[1])
      if (aa[0]=='decelerationLaw'):
        stock['decelerationLaw']=aa[1]
      if (aa[0]=='templateName'):
        stock['templateName']=aa[1]
      if (aa[0]=='emergency'):
        stock['emergency']=float(aa[1])
  if not __debug__:
    print "rollingStock details:"
    print stock
  hasServices=False
#  for aa in trss:
#    if len(aa)>3:
#      hasServices=True
#  if hasServices==True:
#    srvs=initSRVs()
#  else:
#    if not __debug__:
#      print "INFO: no services found..."
  for aa in trss:
    if ((aa[0]!="#") and (cnt==0)):
      found=False
      for asi in sigs[aa[1]]:
         if asi[1]==aa[2]:
           aPos=1000.0*float(asi[0])
      if len(aa)>3: 
        trs=Tr(aa[0],aa[1],aa[3],aPos)
      else:
        trs=Tr(aa[0],aa[1],None,aPos)
    else:
      if (aa[0]!="#"):
        found=False
        for asi in sigs[aa[1]]:
           if asi[1]==aa[2]:
             aPos=1000.0*float(asi[0])
        if len(aa)>3: 
          aT=Tr(aa[0],aa[1],aa[3],aPos)
        else:
          aT=Tr(aa[0],aa[1],None,aPos)
        if aT is not None:
          trs.append(aT)
    cnt=cnt+1 

class Tr:
  global stock
  initSitchSeg=False
  facingSig={}
  trip=0
  BDtiv=0.0  #breaking distance for next TIV
  BDsta=0.0  #fornext station
  DBrt=0.0  #for next realtime event (sig or tvm)
  vapor=0.0  #consumption in kg per second
  coal=0.0  #consumption in kg per second
  consumptionCutOff=1.0
  brakeWear=0.0
  admissionWear=0.0
  mechWear=0.0
  waterQty=0.0
  coalQty=0.0
  indicatedPower=0.0  #in horsepower. n/a for EMUs
  TIVcnt=0
  STAcnt=0
  SIGcnt=0
  pathCnt=-1
  pathBranch=''
  service=None
  name=''
  nextSTA=''
  nextSIG=''
  nextTIV=''
  nSTAx=0.0
  nSIGx=0.0
  nTIVx=0.0
  nTIVvl=0.0
  cTIVvl=0.0
  nTIVtype=''
  maxVk=0.0
  initPos=0.0
  PK=0.0
  aGaussFactor=0.0
  aFull=0.0
  a=0.0
  v=0.0
  x=0.0
  nv=0.0
  cv=0.0
  vK=0.0
  critVk=0.0
  startingPhase=True
  tenderWeight=0.0
  engineWeight=0.0
  carriagesWeight=0.0
  tgtVk=110.0
  deltaBDtiv=0.0
  deltaBDsta=0.0
  advTIV=-1.0
  staBrake=False
  sigBrake=False
  sigPoll=0.0
  sigToPoll={}
  inSta=False
  atSig=False
  react=False
  waitSta=0.0
  waitReact=0.0
  BDzero=0.0
  segment=''
  grade=0.0 # percentage
  gradient=0.0 # angle of inclination, in radian
  oldGradient=0.0
  power=0.0
  m=0.0

  def append(self,aTr):
    self.trs.append(aTr)
  def __iter__(self):
    yield self
    for t in self.trs:
      for i in t:
        yield i

  def switch(self,name,newSegment,initPos):
    if not __debug__:
      print "SWITCHING..."+self.name+" "+name+" from pos "+str(self.x)+" in segment "+self.segment+" to pos "+str(initPos)+" in segment "+newSegment
    self.x=initPos
    self.segment=newSegment
    self.GRDcnt=findMyGRDcnt(initPos,newSegment)
    self.nextGRD=grds[newSegment][self.GRDcnt]
    self.nGRDx=1000.0*float(self.nextGRD[0])
    self.transitionGRDx=self.nGRDx+stock['length']
    self.CRVcnt=findMyCRVcnt(initPos,newSegment)
    self.nextCRV=crvs[newSegment][self.CRVcnt]
    self.nCRVx=1000.0*float(self.nextCRV[0])
    self.transitionCRVx=self.nCRVx+stock['length']
    self.TIVcnt=findMyTIVcnt(initPos,newSegment)
    self.STAcnt=findMySTAcnt(initPos,newSegment)
    self.SIGcnt=findMySIGcnt(initPos,newSegment)
    self.nextSTA=stas[newSegment][self.STAcnt]
    self.nextSIG=sigs[newSegment][self.SIGcnt]
    self.nSTAx=1000.0*float(self.nextSTA[0])
    self.nSIGx=1000.0*float(self.nextSIG[0])
    self.nextTIV=tivs[newSegment][self.TIVcnt]
    if not __debug__:
      print self.name+":t:"+str(t)+" My TIVcnt is: "+str(self.TIVcnt)+" based on pos:"+str(initPos)
      print self.name+":t:"+str(t)+" My STAcnt is: "+str(self.STAcnt)+" based on pos:"+str(initPos)
      print self.name+":t:"+str(t)+" My SIGcnt is: "+str(self.SIGcnt)+" based on pos:"+str(initPos)
      print self.name+":t:"+str(t)+" next TIV at PK"+self.nextTIV[0]+" with limit "+self.nextTIV[1]
      print self.name+":t:"+str(t)+" next GRD at PK"+self.nextGRD[0]+" with grade "+self.nextGRD[1]
    self.nTIVx=1000.0*float(self.nextTIV[0])
    self.nTIVvl=float(self.nextTIV[1])
    self.cTIVvl=0.0
    self.nTIVtype='INC'    # tiv increases speed
    if (self.GRDcnt>0):
      self.grade=float(grds[newSegment][self.GRDcnt-1][1])
    else:
      self.grade=float(grds[newSegment][self.GRDcnt][1])
    self.gradient=self.grade/100.0    #good approx even for grad less than 3.0%
    self.oldGradient=self.gradient
    self.ratioGRD=1.0
    if (self.TIVcnt>0):
      self.maxVk=min(stock['maxSpeed'],float(tivs[newSegment][self.TIVcnt-1][1]))
    else:
      self.maxVk=min(stock['maxSpeed'],float(tivs[newSegment][self.TIVcnt][1]))
    self.redisSIG="sig:"+self.segment+":"+sigs[self.segment][self.SIGcnt][1]
    self.facingSig['seg']=self.segment
    self.facingSig['cnt']=self.SIGcnt
    self.facingSig['type']=sigs[self.segment][self.SIGcnt][2]
    self.facingSig['name']=sigs[self.segment][self.SIGcnt][1]
    previousSig=findPrevSig(self.facingSig)
    if previousSig is None:
      print "FATAL: no previousSig"
      sys.exit()
    if not __debug__:
      print self.name+": facing Sig:"+str(self.facingSig)+" previous Sig:"+str(previousSig)
    self.advSIGcol=r.get(self.redisSIG)
    self.sigSpotted=False
    updateSIGbyTrOccupationWrapper(previousSig,self.name,"red")

  def reinit(self,initSegment,initPos):
    global stock
    global t
    if not __debug__:
      print "REinit..."+self.name+" at pos "+str(initPos)
    gFactor=G*self.gradient
    v2factor=0.0
    self.pathCnt=-1
    self.pathBranch=''
    factors=gFactor+v2factor+stock['railFactor']
    self.startingPhase=True
    self.x=initPos
    self.trip=self.trip+1
    self.coasting=False
    self.segment=initSegment
    self.BDtiv=0.0  #breaking distance for next TIV
    self.BDsta=0.0  #fornext station
    self.DBrt=0.0  #for next realtime event (sig or tvm)
    self.GRDcnt=findMyGRDcnt(initPos,initSegment)
    self.nextGRD=grds[initSegment][self.GRDcnt]
    self.nGRDx=1000.0*float(self.nextGRD[0])
    self.transitionGRDx=self.nGRDx+stock['length']
    self.CRVcnt=findMyCRVcnt(initPos,initSegment)
    self.nextCRV=crvs[initSegment][self.CRVcnt]
    self.nCRVx=1000.0*float(self.nextCRV[0])
    self.transitionCRVx=self.nCRVx+stock['length']
    self.TIVcnt=findMyTIVcnt(initPos,initSegment)
    self.STAcnt=findMySTAcnt(initPos,initSegment)
    self.SIGcnt=findMySIGcnt(initPos,initSegment)
    self.nextSTA=stas[initSegment][self.STAcnt]
    self.nextSIG=sigs[initSegment][self.SIGcnt]
    self.nSTAx=1000.0*float(self.nextSTA[0])
    self.nSIGx=1000.0*float(self.nextSIG[0])
    self.nextTIV=tivs[initSegment][self.TIVcnt]
    if not __debug__:
      print self.name+":t:"+str(t)+" My TIVcnt is: "+str(self.TIVcnt)+" based on pos:"+str(initPos)
      print self.name+":t:"+str(t)+" My STAcnt is: "+str(self.STAcnt)+" based on pos:"+str(initPos)
      print self.name+":t:"+str(t)+" My SIGcnt is: "+str(self.SIGcnt)+" based on pos:"+str(initPos)
      print self.name+":t:"+str(t)+" next TIV at PK"+self.nextTIV[0]+" with limit "+self.nextTIV[1]
      print self.name+":t:"+str(t)+" next GRD at PK"+self.nextGRD[0]+" with grade "+self.nextGRD[1]
    self.nTIVx=1000.0*float(self.nextTIV[0])
    self.nTIVvl=float(self.nextTIV[1])
    self.cTIVvl=0.0
    self.nTIVtype='INC'    # tiv increases speed
    if (self.GRDcnt>0):
      self.grade=float(grds[initSegment][self.GRDcnt-1][1])
    else:
      self.grade=float(grds[initSegment][self.GRDcnt][1])
    self.gradient=self.grade/100.0    #good approx even for grad less than 3.0%
    self.oldGradient=self.gradient
    self.ratioGRD=1.0
    if (self.TIVcnt>0):
      self.maxVk=min(stock['maxSpeed'],float(tivs[initSegment][self.TIVcnt-1][1]))
    else:
      self.maxVk=min(stock['maxSpeed'],float(tivs[initSegment][self.TIVcnt][1]))
    self.PK=self.x
    self.aGaussFactor=aGauss()
    self.aFull=0.0
    self.v=0.0
    self.vK=0.0
    self.nv=0.0
    self.cv=0.0
    if (stock['accelerationLaw']=='EMU1'):
      self.a=getAccForEMU(stock['power'],stock['acceleration'],stock['railFactor'],stock['airFactor'],self.vK,self.m)+self.aGaussFactor
    elif (stock['accelerationLaw']=='STM1'):
      getLiveDataForSTM(self.vK,0.0,self.grade,self.nextCRV[1],self.critVk,self.tgtVk,self.timbre,self.engineWeight,self.tenderWeight,stock['carriagesWeight'],stock['wheelsDiameter'],stock['frontSurface'],stock['driveAxles'],stock['pistonsLength'],stock['cylinders'],stock['expansion'],stock['k'],self.cylinderDiameter,self.startingPhase)+self.aGaussFactor
      self.a=live[0]
#      self.vapor=live[1]
#      self.coal=live[2]
    self.deltaBDtiv=0.0
    self.deltaBDsta=0.0
    self.advTIV=-1.0
    self.staBrake=False
    self.sigBrake=False
    self.inSta=False
    self.atSig=False
    self.react=False
    self.waitSta=0.0
    self.waitReact=0.0
    self.BDzero=0.0
    self.redisSIG="sig:"+self.segment+":"+sigs[self.segment][self.SIGcnt][1]
    self.facingSig['seg']=self.segment
    self.facingSig['cnt']=self.SIGcnt
    self.facingSig['type']=sigs[self.segment][self.SIGcnt][2]
    self.facingSig['name']=sigs[self.segment][self.SIGcnt][1]
    previousSig=findPrevSig(self.facingSig)
    if previousSig is None:
      print "FATAL: no previousSig"
      sys.exit()
    if not __debug__:
      print self.name+": facing Sig:"+str(self.facingSig)+" previous Sig:"+str(previousSig)
    self.advSIGcol=r.get(self.redisSIG)
    self.sigSpotted=False
    updateSIGbyTrOccupationWrapper(previousSig,self.name,"red")

  def dumpstate(self):
    global r
    r.hmset("state:"+self.name,{'t':t,'coasting':self.coasting,'x':self.x,'segment':self.segment,'gradient':self.gradient,'TIV':self.TIVcnt,'SIG':self.SIGcnt,'STA':self.STAcnt,'aFull':self.aFull,'v':self.v,'staBrake':self.staBrake,'sigBrake':self.sigBrake,'inSta':self.inSta,'atSig':self.atSig,'sigSpotted':self.sigSpotted,'maxVk':self.maxVk,'a':self.a,'nextSTA':self.nextSTA[2],'maxPax':stock['maxPax'],'pax':self.pax,'nextSIG':self.nextSIG[1],'nextTIV':self.nextTIV[1],'nTIVtype':self.nTIVtype,'advSIGcol':self.advSIGcol,'redisSIG':self.redisSIG,'units':conf['units'],'react':self.react,'mechWear':self.mechWear,'admissionWear':self.admissionWear,'brakeWear':self.brakeWear,'service':self.service})

  def __init__(self,name,initSegment,service,initPos):
    global r
    global stock
    global srvs
    if not __debug__:
      print "init..."+name+" at pos "+str(initPos)+"with service "+str(service)
    self.maxSquareSpeed=stock['maxSpeed']*stock['maxSpeed']
    self.initSwitchSeg=False
    self.pax=stock['maxPax']
    self.startingPhase=True
    self.critVk=stock['criticalSpeed']
    self.tgtVk=stock['maxSpeed']
    self.m=stock['weight']+self.pax*PAXWEIGHT
    if service is not None:
      found=False
      for ses in srvs:
        if ses[0]==service:
          self.service=ses    
          found=True
      if found==False:
        print str(self.name)+":FATAL: service "+str(service)+" not found in services.txt"
        sys.exit()
    if (stock['accelerationLaw']=='STM1'):
      self.timbre=stock['timbre']
      self.maxTimbre=stock['timbre']
      self.waterQty=stock['waterCapacity']
      self.coalQty=stock['coalCapacity']
      self.engineWeight=stock['driveAxleLoad']*stock['driveAxles']+stock['deadRearAxleLoad']*stock['deadRearAxles']+stock['deadFrontAxleLoad']*stock['deadFrontAxles']
      self.tenderWeight=stock['tenderAxles']*stock['tenderAxleLoad']+self.coalQty+self.waterQty-stock['waterCapacity']-stock['coalCapacity']
      self.m=self.engineWeight+stock['carriagesWeight']+self.tenderWeight
      self.carriagesWeight=stock['carriagesWeight']
      rForIndicated=rollingResistance(self.engineWeight/1000.0,self.tenderWeight/1000.0,stock['carriagesWeight']/1000.0,stock['indicatedGrade'],stock['indicatedCurve'],self.tgtVk,0.0,stock['wheelsDiameter'],stock['frontSurface'],stock['driveAxles'],stock['k'],True)
      self.cylinderPressure=cylinderPressureInKgCm2(stock['timbre'],stock['expansion'])
      self.cylinderDiameter=cylinderDiameterInCm(stock['cylinders'],rForIndicated,stock['wheelsDiameter'],self.cylinderPressure,stock['pistonsLength'])
      self.indicatedPower=indicatedPowerInHorsePower(rForIndicated,self.tgtVk)
      self.vapor=hourlyVaporConsumptionInKg(self.indicatedPower,self.timbre,stock['expansion'])/3600.0
      self.coal=hourlyCoalConsumptionInKg(self.vapor)
    gFactor=G*self.gradient
    v2factor=0.0
    self.pathCnt=-1
    self.pathBranch=''
    factors=gFactor+v2factor+stock['railFactor']
    self.trs=[]
    self.trip=0
    self.coasting=False
    self.x=initPos
    self.name=name
    self.segment=initSegment
    self.BDtiv=0.0  #breaking distance for next TIV
    self.BDsta=0.0  #fornext station
    self.DBrt=0.0  #for next realtime event (sig or tvm)
#    self.gradient=math.atan(self.grade/100.0)
    self.GRDcnt=findMyGRDcnt(initPos,initSegment)
    self.CRVcnt=findMyCRVcnt(initPos,initSegment)
    self.TIVcnt=findMyTIVcnt(initPos,initSegment)
    self.STAcnt=findMySTAcnt(initPos,initSegment)
    self.SIGcnt=findMySIGcnt(initPos,initSegment)
    if stock['length']>initPos:
      print "FATAL: "+str(self.name)+" must be located at least at x:"+str(stock['length'])+". Currently it is located at x:"+str(initPos)
      sys.exit()
    self.nextSTA=stas[initSegment][self.STAcnt]
    self.nextSIG=sigs[initSegment][self.SIGcnt]
    self.nextGRD=grds[initSegment][self.GRDcnt]
    self.nextCRV=crvs[initSegment][self.CRVcnt]
    self.nSTAx=1000.0*float(self.nextSTA[0])
    self.nSIGx=1000.0*float(self.nextSIG[0])
    self.nGRDx=1000.0*float(self.nextGRD[0])
    self.nCRVx=1000.0*float(self.nextCRV[0])
    self.transitionGRDx=self.nGRDx+stock['length']
    self.transitionCRVx=self.nCRVx+stock['length']
    self.nextTIV=tivs[initSegment][self.TIVcnt]
    if not __debug__:
      print self.name+":t:"+str(t)+" MyGRDcnt is:"+str(self.GRDcnt)
      print self.name+":t:"+str(t)+" My TIVcnt is: "+str(self.TIVcnt)+" based on pos:"+str(initPos)
      print self.name+":t:"+str(t)+" My STAcnt is: "+str(self.STAcnt)+" based on pos:"+str(initPos)
      print self.name+":t:"+str(t)+" My SIGcnt is: "+str(self.SIGcnt)+" based on pos:"+str(initPos)
      print self.name+":t:"+str(t)+" next TIV at PK"+self.nextTIV[0]+" with limit "+self.nextTIV[1]
      print self.name+":t:"+str(t)+" next GRD at PK"+self.nextGRD[0]+" with limit "+self.nextGRD[1]
    self.nTIVx=1000.0*float(self.nextTIV[0])
    self.nTIVvl=float(self.nextTIV[1])
    self.cTIVvl=0.0
    self.nTIVtype='INC'    # tiv increases speed
    if (self.TIVcnt>0):
      self.maxVk=min(stock['maxSpeed'],float(tivs[initSegment][self.TIVcnt-1][1]))
    else:
      self.maxVk=min(stock['maxSpeed'],float(tivs[initSegment][self.TIVcnt][1]))
    if (self.GRDcnt>0):
      self.grade=float(grds[initSegment][self.GRDcnt-1][1])
    else:
      self.grade=float(grds[initSegment][self.GRDcnt][1])
    #self.gradient=math.atan(self.grade/100.0)
    self.gradient=self.grade/100.0
    self.oldGradient=self.gradient
    self.ratioGRD=1.0
    self.PK=self.x
    self.aGaussFactor=aGauss()
    self.aFull=0.0
    self.v=0.0
    self.vK=0.0
    self.nv=0.0
    self.cv=0.0
    if (stock['accelerationLaw']=='EMU1'):
      self.a=getAccForEMU(stock['power'],stock['acceleration'],stock['railFactor'],stock['airFactor'],self.vK,self.m)+self.aGaussFactor
    elif (stock['accelerationLaw']=='STM1'):
      getLiveDataForSTM(self.vK,0.0,self.grade,self.nextCRV[1],self.critVk,self.tgtVk,self.timbre,self.engineWeight,self.tenderWeight,stock['carriagesWeight'],stock['wheelsDiameter'],stock['frontSurface'],stock['driveAxles'],stock['pistonsLength'],stock['cylinders'],stock['expansion'],stock['k'],self.cylinderDiameter,self.startingPhase)+self.aGaussFactor
      self.a=live[0]
#      self.vapor=live[1]
#      self.coal=live[2]
    self.deltaBDtiv=0.0
    self.deltaBDsta=0.0
    self.advTIV=-1.0
    self.staBrake=False
    self.sigBrake=False
    self.inSta=False
    self.atSig=False
    self.waitSta=0.0
    self.BDzero=0.0
    self.redisSIG="sig:"+self.segment+":"+sigs[self.segment][self.SIGcnt][1]
    self.facingSig['seg']=self.segment
    self.facingSig['cnt']=self.SIGcnt
    self.facingSig['type']=sigs[self.segment][self.SIGcnt][2]
    self.facingSig['name']=sigs[self.segment][self.SIGcnt][1]
    previousSig=findPrevSig(self.facingSig)
    if previousSig is None:
      print "FATAL: no previousSig"
      sys.exit()
    if not __debug__:
      print self.name+": facing Sig:"+str(self.facingSig)+" previous Sig:"+str(previousSig)
    self.advSIGcol="red"   # safeguard before we run step()
    self.sigSpotted=False
    sigAlreadyOccupied=r.get("sig:"+previousSig['seg']+":"+previousSig['name']+":isOccupied")
    if sigAlreadyOccupied is not None:
      if sigAlreadyOccupied!=self.name:
        print "IGNORED: "+str(self.name)+" and "+str(sigAlreadyOccupied)+" share the same signal block"
        return None
    else:
      if (sigs[self.segment][self.SIGcnt][2]=='2'):
        print "FATAL: "+str(self.name)+" is facing a Type 2 signal. It should rather face the next signal (a type 5)"
        sys.exit()    
    r.set("sig:"+previousSig['seg']+":"+previousSig['name']+":isOccupied",self.name)
    r.set("sig:"+previousSig['seg']+":"+previousSig['name'],"red")
    updateSIGbyTrOccupationWrapper(previousSig,self.name,"red")

  def step(self):
    global t
    global exitCondition
    global stock
    global live
    removeTr=False
    self.initSwitchSeg=False
    gFactor=G*self.gradient
    vSquare=self.v*self.v
    v2factor=(stock['airFactor']*vSquare)
    mv=self.m*self.v
    if (ncyc%CYCLE==0):
      self.aGaussFactor=aGauss()
      self.consumptionCutOff=1.0
      if (stock['accelerationLaw']=='STM1'):
        if gFactor<-0.05:
          self.consumptionCutOff=1.0-gFactor+(gFactor/-0.05)
        elif gFactor<0.0:
          self.consumptionCutOff=1.0-gFactor
        if self.consumptionCutOff>4.5:
            self.consumptionCutOff=4.5
        if not __debug__:
          print self.name+":"+str(t)+":PK:"+str(self.PK)+":updating coal and water weight before: "+str(self.waterQty)+" "+str(self.coalQty)+" "+str(self.tenderWeight)
        self.waterQty=self.waterQty-(self.vapor/self.consumptionCutOff)
        self.coalQty=self.coalQty-(self.coal/self.consumptionCutOff)
        self.tenderWeight=stock['tenderAxles']*stock['tenderAxleLoad']+self.coalQty+self.waterQty-stock['waterCapacity']-stock['coalCapacity']
        self.m=self.engineWeight+stock['carriagesWeight']+self.tenderWeight
        if ((self.coalQty<=0.0) or (self.waterQty<=0.0)):
          print self.name+":"+str(t)+":FATAL run out of resources! coal="+str(self.coalQty)+"kg, water: "+str(self.waterQty)+"kg"
          sys.exit()
#
# STAGE 1 : main acc updates
#
    if (self.x>=(self.nGRDx)):
      if not __debug__:
        print self.name+":"+str(t)+":PASSING BY GRD "+self.segment+":"+" vK:"+str(self.vK)+" at x:"+str(self.nGRDx)+" with GRD:"+self.nextGRD[1]
      self.transitionGRDx=self.nGRDx+stock['length']
      self.oldGradient=self.gradient
      self.gradient=float(self.nextGRD[1])/100.0
      if (self.GRDcnt<len(grds[self.segment])-1):
        self.GRDcnt=self.GRDcnt+1 
        self.nextGRD=grds[self.segment][self.GRDcnt] 
        self.nGRDx=1000.0*float(self.nextGRD[0])
        if not __debug__:
          print self.name+":t:"+str(t)+"next GRD (value "+self.nextGRD[1]+") at x:"+str(self.nGRDx)+" with transition at x:"+str(self.transitionGRDx)
      else:
        if not __debug__:
          print self.name+":t:"+str(t)+":no more GRDS on segment "+self.segment
        self.nGRDx=sys.maxsize
        self.transitionGRDx=sys.maxsize
      if not __debug__:
        print self.name+":t:"+str(t)+":next GRD change is at x:"+str(self.nGRDx)
    if (self.x>=(self.nCRVx)):
      if not __debug__:
        print self.name+":"+str(t)+":PASSING BY CRV "+self.segment+":"+" vK:"+str(self.vK)+" at x:"+str(self.nCRVx)+" with CRV:"+self.nextCRV[1]
      self.transitionCRVx=self.nCRVx+stock['length']
      if (self.CRVcnt<len(crvs[self.segment])-1):
        self.CRVcnt=self.CRVcnt+1 
        self.nextCRV=crvs[self.segment][self.CRVcnt] 
        self.nCRVx=1000.0*float(self.nextCRV[0])
        if not __debug__:
          print self.name+":t:"+str(t)+"next CRV (value "+self.nextCRV[1]+") at x:"+str(self.nCRVx)+" with transition at x:"+str(self.transitionCRVx)
      else:
        if not __debug__:
          print self.name+":t:"+str(t)+":no more CRVS on segment "+self.segment
        self.nCRVx=sys.maxsize
        self.transitionCRVx=sys.maxsize
      if not __debug__:
        print self.name+":t:"+str(t)+":next CRV change is at x:"+str(self.nCRVx)
    if (ncyc%5==0):  # perform grade calculations every 5 cycles
      if (self.x>=(self.transitionGRDx-stock['length'])):
        if (self.x<=self.transitionGRDx):
          self.ratioGRD=(self.transitionGRDx-self.x)/(stock['length'])
          gFactor=G*self.oldGradient*self.ratioGRD+G*self.gradient*(1.0-self.ratioGRD)
          if not __debug__:
            if (self.v>0.0): 
              print self.name+":t:"+str(t)+":GRD progress:"+str(self.ratioGRD)+" x:"+str(self.x)+" gFactor:"+str(gFactor)+" oldGRD:"+str(self.oldGradient)+" newGRD:"+str(self.gradient)+" ratio:"+str(self.ratioGRD)
    factors=v2factor+gFactor+stock['railFactor']
    dcc=stock['deceleration']-gFactor
    if (dcc<stock['deceleration']):  #since DCC is always negative...
      dcc=stock['deceleration']
    self.BDzero=-(self.v*self.v)/(2*(dcc))
    if ((self.staBrake==False) and (self.x>=(self.nSTAx-self.BDzero))):
      if not __debug__:
        print self.name+":t:"+str(t)+":ADVANCE STA x:"+str(self.nSTAx)+" vK:"+str(self.vK)
      self.staBrake=True
      self.a=dcc-gFactor#+aGauss()
    if ((self.staBrake==True) and (self.vK<=0.8)):
      self.a=-0.00004#-gFactor
    elif (self.staBrake==True):
      self.a=dcc
    if ((self.sigSpotted==False) and (self.x>=(self.nSIGx-self.BDzero))):
      self.redisSIG="sig:"+self.segment+":"+sigs[self.segment][self.SIGcnt][1]
      self.advSIGcol=r.get(self.redisSIG)
      isOc=r.get(self.redisSIG+":isOccupied")
      if isOc is not None:
        self.advSIGcol="red"
        r.set(self.redisSIG,"red")
      if not __debug__:
        print self.name+":t:"+str(t)+":ADVANCE "+self.advSIGcol+" SIG vK:"+str(self.vK)+" "+self.redisSIG+" isOccupied? "+str(isOc)
      self.sigSpotted=True
      if (self.advSIGcol=="red"):
        self.a=dcc
        self.sigBrake=True
    if ((self.sigBrake==True) and (self.vK<=0.7)):
      self.a=-0.00004#-gFactor
    if ((self.atSig==False) and (self.x>=(self.nSIGx))): # abeam signal
      self.facingSig['seg']=self.segment
      self.facingSig['cnt']=self.SIGcnt
      self.facingSig['type']=sigs[self.segment][self.SIGcnt][2]
      self.facingSig['name']=sigs[self.segment][self.SIGcnt][1]
      if (self.SIGcnt==(len(sigs[self.segment])-1)): #no more sigs
        if ((sigs[self.segment][self.SIGcnt][2]!='2') and (sigs[self.segment][self.SIGcnt][2]!='4C')):
          removeTr=True
      if (self.sigSpotted==True):
        self.sigSpotted=False
      if (self.sigBrake==True):
        self.sigBrake=False
        if ((self.vK<0.0) or (self.vK>4.0)):
          print self.name+":t:"+str(t)+" **** FATAL AT SIG "+self.nextSIG[1]+" **** PK:"+str(self.PK)+" vK:"+str(self.vK)+" maxVk:"+str(self.maxVk)+" aF:"+str(self.aFull)+" a:"+str(self.a)+" power: "+str(self.power)+" v2factor: "+str(v2factor)+" gFactor:"+str(gFactor)+" vSquare:"+str(vSquare)
          sys.exit()
        self.a=0.0
        self.v=0.0
        self.vK=0.0
        if (sigs[self.segment][self.SIGcnt][2]=='2'):
          if not __debug__:
            print self.name+":t:"+str(t)+"Buffer reached. Initiating reverse sequence" 
          kCur=r.get("switch:"+sigs[self.segment][self.SIGcnt][1]+":position")
          kRev=r.get("switch:"+sigs[self.segment][self.SIGcnt][1]+":reversePosition")
          kFor=r.get("switch:"+sigs[self.segment][self.SIGcnt][1]+":forwardPosition")
          if not __debug__:
            print "current switch pos: "+str(kCur)
          kOld=kCur
          if (kOld!=self.segment):
            kCur=kOld
          else:
            if (kOld==kRev):
              kCur=kFor
            else:
              kCur=kRev
          if not __debug__:
            print "new switch pos: "+str(kCur)
            r.set("switch:"+sigs[self.segment][self.SIGcnt][1]+":position",kCur)
          if not __debug__:
            print "switch locked in position "+kCur
            print self.name+":delta buffer: "+str(-self.nSIGx+self.x)
          p={}
          p['seg']=self.segment
          p['cnt']=self.SIGcnt
          p['type']=sigs[self.segment][self.SIGcnt][2]
          previousSig=findPrevSig(p)
          if previousSig is None:
            print "FATAL: no previousSig"
            sys.exit()
          previousPreviousSig=findPrevSig(previousSig)
          updateSIGbyTrOccupationWrapper(p,self.name,"green")
          updateSIGbyTrOccupationWrapper(previousSig,self.name,"green")
          if previousPreviousSig is not None:
            updateSIGbyTrOccupationWrapper(previousPreviousSig,self.name,"green")
          self.reinit(kCur,stock['length']-self.nSIGx+self.x)
        else: 
          self.atSig=True
          self.sigPoll=t+SIGPOLL
          self.sigToPoll['longName']="sig:"+self.segment+":"+sigs[self.segment][self.SIGcnt][1]
          self.sigToPoll['seg']=self.segment
          self.sigToPoll['cnt']=self.SIGcnt
          self.sigToPoll['name']=sigs[self.segment][self.SIGcnt][1]
          self.sigToPoll['type']=sigs[self.segment][self.SIGcnt][2]
          if not __debug__:
            print self.name+":t:"+str(t)+" waiting at sig..."+str(self.sigToPoll)
      else:   #sigBrake is False
        if not __debug__:
          print self.name+":t:"+str(t)+":PASSING BY SIG "+self.segment+":"+self.nextSIG[1]+" vK:"+str(self.vK)
        checkSig=findSuccSig(self.facingSig)
        if 'type' in checkSig:
          if checkSig['type']=='6':
            attemptLock4C(checkSig,self.name)
        if self.nextSIG[2]=='6':  #sig type 6
          if not __debug__:
            print str(self.name)+":ABEAM sig 6, facing:"+str(self.facingSig)+" nextSIG:"+str(self.nextSIG)
          attemptLock4C(self.facingSig,self.name)
        if self.nextSIG[2]=='4C':  #sig type 4C 
          if not __debug__:
            print str(self.name)+":ABEAM sig 4C, facing:"+str(self.facingSig)+" nextSIG:"+str(self.nextSIG)
          kPeer=getSigPeer(self.facingSig)
          kMainPos=r.get("switch:"+sigs[self.segment][self.facingSig['cnt']][1]+":mainPosition")
          if kMainPos==kPeer['seg']:
            kPeerX=1000.0*float(sigs[kPeer['seg']][kPeer['cnt']][0])
#            print "facing:"+str(self.facingSig)
#            print "kPeer:"+str(kPeer)
#            print "kPeerX:"+str(kPeerX)
            deltaX=kPeerX+self.x-self.nSIGx
#          kBranch=r.get("switch:"+sigs[self.segment][self.facingSig['cnt']][1]+":mainPosition")
            kBranch=kPeer['seg']
            self.pathBranch=kBranch
#            print str(self.name)+"initSwitchSeg SET"
            self.initSwitchSeg=True
        if self.nextSIG[2]=='4D':  #sig type 4D 
          if not __debug__:
            print str(self.name)+":ABEAM sig 4D, facing:"+str(self.facingSig)+" nextSIG:"+str(self.nextSIG)
          self.pathCnt=self.pathCnt+1
          kMain=r.get("switch:"+sigs[self.segment][self.facingSig['cnt']][1]+":mainPosition")
          kBranch=r.get("switch:"+sigs[self.segment][self.facingSig['cnt']][1]+":branchPosition")
          if self.segment==kMain:
            tgtSeg='Branch'
          elif self.segment==kBranch:
            tgtSeg='Main'
          else:
            print "FATAL: unknown branch..."+kMain+"..."+kBranch
            sys.exit()
          deltaX=-self.nSIGx+self.x
          found=False
          if self.service is not None:
            for asv in self.service:
#              print str(self.name)+":asv:"+str(asv)
              asp=asv.split(":")
#              print "asp:"+str(asp)+" asp0:"+str(asp[0])
              if asp[0]==self.facingSig['name']:
                found=True
                if asp[1]=='Main':
                  self.pathBranch=kMain
                elif asp[1]=='Right':
                  self.pathBranch=kBranch
#                  print str(self.name)+"initSwitchSeg SET"
                  self.initSwitchSeg=True
                elif asp[1]=='Left':
                  self.pathBranch=kBranch
#                  print str(self.name)+"initSwitchSeg SET"
                  self.initSwitchSeg=True
                else:
                  print "FATAL... unknown branch..."+asp[1]
                  sys.exit()
          if found==False:  #By default, assume we take the Main branch
            self.pathBranch=kMain
        if (self.SIGcnt<len(sigs[self.segment])-1):
          if not __debug__:
            print str(self.name)+":SIG increase notification,segment:"+self.segment+" SIGcnt:"+str(self.SIGcnt)
            print "..self.nextSIG before:"+str(self.nextSIG)
            print "..self.facingSig before:"+str(self.facingSig)
          self.SIGcnt=self.SIGcnt+1 
          self.nextSIG=sigs[self.segment][self.SIGcnt] 
          self.facingSig['seg']=self.segment
          self.facingSig['cnt']=self.SIGcnt
          self.facingSig['type']=sigs[self.segment][self.SIGcnt][2]
          self.facingSig['name']=sigs[self.segment][self.SIGcnt][1]
          if not __debug__:
            print str(self.name)+":SIG increase notification,segment:"+self.segment+" SIGcnt:"+str(self.SIGcnt)
            print "..self.nextSIG after:"+str(self.nextSIG)
            print "..self.facingSig after:"+str(self.facingSig)
          if not __debug__:
            print self.name+":t:"+str(t)+"next SIG ("+self.nextSIG[1]+") at PK"+self.nextSIG[0]
          self.nSIGx=1000.0*float(self.nextSIG[0])
          p={}
          p['seg']=self.segment
          p['cnt']=self.SIGcnt
          p['type']=sigs[self.segment][self.SIGcnt][2]
          previousSig=findPrevSig(p)
          if not __debug__:
            print str(self.name)+":previousSig of "+str(p)+" is "+str(previousSig)
          if previousSig is not None:
            updateSIGbyTrOccupationWrapper(previousSig,self.name,"red")
        else:
          if not __debug__:
            print "No more SIGS for "+self.name+":t:"+str(t)+":PASSING BY SIG "+self.segment+":"+self.nextSIG[1]+" vK:"+str(self.vK)
    elif (self.atSig==True):
      self.a=0.0
      self.v=0.0
      self.vK=0.0
    if (self.x>=(self.nSTAx)):
      if ((self.vK<0.0) or (self.vK>4.0)):
        print str(t)+":"+str(self.name)+":FATAL at STA"
        sys.exit()
      self.inSta=True
      if stock['accelerationLaw']=='STM1': # replenish stocks
        if not __debug__:
          print self.name+":t:"+str(t)+":REPLENISH BEFORE"+str(self.coalQty)+"kg, water: "+str(self.waterQty)+"kg"
        self.waterQty=stock['waterCapacity']
        self.coalQty=stock['coalCapacity']
        if not __debug__:
          print self.name+":t:"+str(t)+":REPLENISH AFTER"+str(self.coalQty)+"kg, water: "+str(self.waterQty)+"kg"
#      if STAPROGRESS==True:
#        print str(self.name)+','+str(self.trip)+","+str(t)+','+str(self.nextSTA[1])
      self.waitSta=t+stock['waitTime']
      self.staBrake=False 
      if not __debug__:
        print self.name+":t:"+str(t)+":IN STA "+self.nextSTA[1]+" vK:"+str(self.vK)+" a:"+str(self.a)
      self.a=0.0
      self.v=0.0
      self.vK=0.0
      if ((self.nextSTA[1]=='W') or (self.nextSTA[1]=='E')):
        exitCondition=True
      else:
        if (self.STAcnt<len(stas[self.segment])-1):
          self.STAcnt=self.STAcnt+1 
          self.nextSTA=stas[self.segment][self.STAcnt] 
          if not __debug__:
            print self.name+":t:"+str(t)+":next STA ("+self.nextSTA[1]+") at PK"+self.nextSTA[0]
          self.nSTAx=1000.0*float(self.nextSTA[0])
        else:
          if not __debug__:
            print self.name+":t:"+str(t)+":no more STAS on segment "+self.segment
          self.nSTAx=sys.maxsize
    if (self.nTIVtype=='DEC'):
      self.deltaBDtiv=self.BDtiv
    else:
      self.deltaBDtiv=0.0
    if ((self.advTIV>0.0) and (self.x>=self.advTIV)):
      self.advTIV=-1.0
      if not __debug__:
        print self.name+":t:"+str(t)+":TIV "+str(self.TIVcnt-1)+" reached at curr speed "+str(self.vK)+", maxVk now "+str(self.maxVk)
    if (self.x>=self.nTIVx-self.deltaBDtiv):
      self.maxTIV=self.nTIVvl
      self.maxVk=min(self.maxTIV,maxLine,stock['maxSpeed'])
      if (self.nTIVtype=='DEC'):
        if not __debug__:
          print self.name+":t:"+str(t)+":ADVANCE TIV "+str(self.TIVcnt)+" reached at curr speed "+str(self.vK)+", maxVk will be "+str(self.maxVk)
        self.advTIV=self.nTIVx
      else:
        if not __debug__:
          print self.name+":t:"+str(t)+":TIV "+str(self.TIVcnt)+" reached at curr speed "+str(self.vK)+", maxVk now "+str(self.maxVk)
      if (self.TIVcnt<len(tivs[self.segment])-1):
        self.TIVcnt=self.TIVcnt+1
        self.nextTIV=tivs[self.segment][self.TIVcnt]
        self.cTIVvl=self.nTIVvl
        self.nTIVx=1000.0*float(self.nextTIV[0])
        self.nTIVvl=float(self.nextTIV[1])
        if (self.nTIVvl>self.cTIVvl):
          self.nTIVtype='INC'
        else:
          self.nTIVtype='DEC'  # next TIV decreases speed
          self.nv=self.nTIVvl/3.6
          self.cv=self.cTIVvl/3.6
          self.BDtiv=((self.nv*self.nv)-(self.cv*self.cv))/(2*stock['deceleration'])
          self.BDtiv=1.5*self.BDtiv   # safety margin
        if not __debug__:
          print self.name+":t:"+str(t)+"  next TIV at PK"+self.nextTIV[0]+" with limit "+self.nTIVtype+self.nextTIV[1]+" (currspeed:"+str(self.vK)+")"
        if (self.nTIVvl<self.cTIVvl):
          if not __debug__:
            print self.name+":t:"+str(t)+"  BDtiv: "+str(self.BDtiv)
      else:
        self.nTIVx=sys.maxsize
    if ((self.staBrake==False) and (self.sigBrake==False) and (self.maxVk>self.vK)):
#      if not __debug__:
#        print self.name+":t:"+str(t)+":vK:"+str(self.vK)+" maxVk:"+str(self.maxVk)+" =>ready to acc" 
      self.a=10.0 #any arbitrary value as long as it is positive
    if (self.maxVk<self.vK):
#      if not __debug__:
#        print self.name+":t:"+str(t)+":vK:"+str(self.vK)+" maxVk:"+str(self.maxVk)+" =>ready to dcc"
      self.a=-10.0  #any arbitrary value as long as it is neg
#
# STAGE 2 : other acc updates
#
    if ((self.maxVk>20.0) and (self.advSIGcol=="yellow")):
      auxMaxVk=0.65*self.maxVk
      if ((self.vK>20.0) and (auxMaxVk<self.vK)):
        if not __debug__:
          if (ncyc%CYCLE==0):
            print self.name+":t:"+str(t)+":vK:"+str(self.vK)+" maxVk:"+str(self.maxVk)+" =>ready to dcc to "+str(auxMaxVk)+" due to yellow"
        a=-10.0
    else:
      auxMaxVk=self.maxVk
    self.coasting=False
    if (self.a>0.0):
      if ((self.gradient<0.0025) and (self.vK>auxMaxVk*VTHRESH)):
        if not __debug__:
          if (ncyc%CYCLE==0):
            print self.name+":t:"+str(t)+":coasting at "+str(self.vK)
        self.coasting=True
        self.a=0.0
      else:
        if (self.vK<=(auxMaxVk*VTHRESH)):
          if (stock['accelerationLaw']=='EMU1'):
            self.a=getAccForEMU(stock['power'],stock['acceleration'],stock['railFactor'],stock['airFactor'],self.vK,self.m)
          elif (stock['accelerationLaw']=='STM1'):
            getLiveDataForSTM(self.vK,0.0,self.grade,self.nextCRV[1],self.critVk,self.tgtVk,self.timbre,self.engineWeight,self.tenderWeight,stock['carriagesWeight'],stock['wheelsDiameter'],stock['frontSurface'],stock['driveAxles'],stock['pistonsLength'],stock['cylinders'],stock['expansion'],stock['k'],self.cylinderDiameter,self.startingPhase)
            self.a=live[0]
#            self.vapor=live[1]
#            self.coal=live[2]
          else:
            print "FATAL: ALAW unknown"
            sys.exit()
          if (self.a>stock['acceleration']):
            print "FATAL ACC "+str(self.a)
            sys.exit()
          if not __debug__:
            if (ncyc%CYCLE==0):
              print self.name+":t:"+str(t)+":need to go faster..."+str(self.a)+" "+str(self.x)+" "+str(self.vK)
        else:
          self.a=0.0 
    elif (self.a<0.0):
      if ((self.staBrake==False) and (self.sigBrake==False) and (self.vK<auxMaxVk)):
        self.a=0.0
      else:
        if (auxMaxVk<self.vK):
          self.a=dcc
    else:  # a=0.0
      if ((self.staBrake==False) and (self.sigBrake==False) and (self.atSig==False) and (self.inSta==False) and (self.react==False) and (self.vK<0.910*auxMaxVk)):
        if not __debug__:
          print self.name+":t:"+str(t)+":boosting from vK:"+str(self.vK)+" to maxVk:"+str(auxMaxVk)+" with aFull:"+str(self.aFull)
        if (stock['accelerationLaw']=='EMU1'):
          self.a=getAccForEMU(stock['power'],stock['acceleration'],stock['railFactor'],stock['airFactor'],self.vK,self.m)+aGauss()
        elif (stock['accelerationLaw']=='STM1'):
          getLiveDataForSTM(self.vK,0.0,self.grade,self.nextCRV[1],self.critVk,self.tgtVk,self.timbre,self.engineWeight,self.tenderWeight,stock['carriagesWeight'],stock['wheelsDiameter'],stock['frontSurface'],stock['driveAxles'],stock['pistonsLength'],stock['cylinders'],stock['expansion'],stock['k'],self.cylinderDiameter,self.startingPhase)+aGauss()
          self.a=live[0]
#          self.vapor=live[1]
#          self.coal=live[2]
      elif (self.vK>4.0):
        self.coasting=True
        if not __debug__:
          if (ncyc%CYCLE==0):
            print self.name+":t:"+str(t)+":coasting at "+str(self.vK)
#
# STAGE 3 : calculate aFull
#
    if (self.a>=0.0):
      if stock['accelerationLaw']=='STM1':
        self.aFull=self.a-gFactor
      else:
        self.aFull=self.a-gFactor
      if (self.aFull<0.0):
        if ((self.v+(self.aFull/CYCLE))<0.0):
          if (self.v>0.0):
            print "FATAL neg speed. aF: "+str(self.aFull)+" vK:"+str(self.vK)+" v:"+str(self.v)
            sys.exit()
          elif ((self.v==0.0) or (self.inSta==True) or (self.atSig==True) or (self.react==True)):   # train is stopped at sig or sta
             self.aFull=0.0
             self.a=0.0
             self.v=0.0
          else:
            print "FATAL neg speed. aF: "+str(self.aFull)+" vK:"+str(self.vK)+" v:"+str(self.v)
            sys.exit()
    else:   #negative a
      self.aFull=self.a
      if (self.aFull>0.0):
        self.aFull=0.0 
    if ((self.inSta==True) or (self.atSig==True) or (self.react==True)):
      self.v=0.0
      self.a=0.0
      self.aFull=0.0 
    self.v=self.v+(self.aFull/CYCLE)
    if (self.v<0.0):
      self.v=0.0
      self.a=0.0
      self.aFull=0.0
    self.vK=self.v*3.6
    self.x=self.x+(self.v/CYCLE)
    self.PK=self.x/1000.0
    if (self.a<0):
      self.brakeWear=self.brakeWear+(self.a*self.a)
    wearV=self.v-(0.5*stock['maxSpeed'])
    # source: https://books.google.fr/books?id=XRAAAAAAMAAJ&pg=PA218&lpg=PA218&dq=locomotive+vapeur+consommation+en+descente&source=bl&ots=GJLYUcBVHy&sig=U9sx-4ZghgfdOBYMje3cZJRqwm0&hl=fr&sa=X&ved=0ahUKEwidiPGtla3aAhXCbFAKHVusA6cQ6AEIeTAM#v=onepage&q=locomotive%20vapeur%20consommation%20en%20descente&f=false
    if wearV>0:
      wearV=(wearV*wearV)/self.maxSquareSpeed
    else:
      wearV=0.0
    if (float(self.nextCRV[0])>0.0):
      self.mechWear=self.mechWear+0.1*self.v*(750.0/float(self.nextCRV[0]))
    else:
      self.mechWear=self.mechWear+0.1*self.v
#    self.mechWear=self.mechWear+wearV+self.v
    self.admissionWear=self.admissionWear+(1.0/(self.consumptionCutOff))

# 
# STAGE 4 : perform coarse grain calculations
#
    if (ncyc%CYCLE==0):
# here make coarse-grain markers calculation
# power calculation:
      self.power=self.m*self.a*self.v+factors*self.v
      if (self.power<0.0):
        self.power=0.0
      if not __debug__:
        if (realTime==False):
          print self.name+":t:"+str(t)+" State update PK:"+str(self.PK)+" vK:"+str(self.vK)+" maxVk:"+str(auxMaxVk)+" aF:"+str(self.aFull)+" a:"+str(self.a)+" power: "+str(self.power)+" v2factor: "+str(v2factor)+" gFactor:"+str(gFactor)+" factors:"+str(factors)+" vSquare:"+str(vSquare)+" inSta?"+str(self.inSta)+" STA:"+str(self.nextSTA)+" atSig?"+str(self.atSig)+" SIG:"+str(self.nextSIG)+" sigBrake?"+str(self.sigBrake)+" staBrake?"+str(self.staBrake)+" curv?"+self.nextCRV[1]
#        if TPROGRESS==True:
#          print str(self.name)+','+str(self.trip)+","+str(t)+','+str(self.PK)+","+str(self.vK)+","+str(self.aFull)+","+str(self.power)

#
# STAGE 5 : manage phases when train is stopped
#
    if (self.inSta==True):
      self.a=0.0
      self.v=0.0
      self.vK=0.0
      if (t>=self.waitSta):
        headway=r.get("headway:"+self.segment+":"+self.nextSTA[1])
        if headway is None:
          self.inSta=False
          self.waitSta=0.0
          self.react=True
          self.waitReact=t+longTail(9.3,71.0,30.0)
          if not __debug__:
            print self.name+":t:"+str(t)+":OUT STA, a:"+str(self.a)+" vK:"+str(self.vK)+", reaction: "+str(self.waitReact-t)
            if ((self.waitReact-t)>10.0):
              print self.name+":t:"+str(t)+":REACTION BURST:"+str(self.waitReact-t)
        else:
          self.waitSta=self.waitSta+2.0
          if not __debug__:
            print self.name+":t:"+str(t)+":waiting for headway "+"headway:"+self.segment+":"+self.nextSTA[1]
    if (self.atSig==True):
      self.a=0.0
      self.v=0.0
      self.vK=0.0
      if (t>self.sigPoll):
        if (self.sigToPoll['type']=='4C'):  #type 4C
          if not __debug__:
            print str(self.name)+":in sigPoll, attempting to unlock 4C"
            print "sigToPoll: "+str(self.sigToPoll)+" and facing:"+str(self.facingSig)+" and nextSIG:"+str(self.nextSIG)
          checkSig=findPrevSig(self.sigToPoll)  #to get the type 6
          if not __debug__:
            print "checkSig: "+str(checkSig)
          attemptLock4C(checkSig,self.name)
        k=r.get(self.sigToPoll['longName']+":isOccupied")
        if (k==self.name):
          k=None
#        if (ncyc%CYCLE==0):
#          print self.name+":t:"+str(t)+" waiting at sig..."+self.sigToPoll+" currently:"+k
        if (self.sigToPoll['type']=='2'):  #type 2
          kpos=r.get("switch:"+self.sigToPoll['name']+":position")
          if not __debug__:
            print self.name+":t:"+str(t)+":next SIG to poll is a type 2:"
            print str(self.sigToPoll)
            print "  switch position:"+str(kpos)
          if (k is None):
            r.set("switch:"+self.sigToPoll['name'],self.segment)
            kpos=r.get("switch:"+self.sigToPoll['name']+":position")
            if not __debug__:
              print "  switch NEW position:"+str(kpos)
        if k is None:
          self.atSig=False
          self.react=True
          self.waitReact=t+longTail(9.3,71.0,30.0)
          if not __debug__:
            print self.name+":t:"+str(t)+":OUT SIG, a:"+str(self.a)+", reaction:"+str(self.waitReact-t)
          if ((self.waitReact-t)>10.0):
            print self.name+":t:"+str(t)+":REACTION BURST:"+str(self.waitReact-t)
        else:
          if not __debug__:
            print self.name+":t:"+str(t)+":UPSIG "+str(self.sigToPoll)+" is OCCUPIED BY:"+str(k)
          self.sigPoll=t+SIGPOLL
    if (self.react==True):
      self.a=0.0
      self.v=0.0
      self.vK=0.0
      if (t>=self.waitReact):
        self.react=False
        r.set("headway:"+self.segment+":"+self.nextSTA[1],True)
        r.expire("headway:"+self.segment+":"+self.nextSTA[1],CLOCKHEADWAY)
        if (stock['accelerationLaw']=='EMU1'):
          self.a=getAccForEMU(stock['power'],stock['acceleration'],stock['railFactor'],stock['airFactor'],self.vK,self.m)+aGauss()
        elif (stock['accelerationLaw']=='STM1'):
          getLiveDataForSTM(self.vK,0.0,self.grade,self.nextCRV[1],self.critVk,self.tgtVk,self.timbre,self.engineWeight,self.tenderWeight,stock['carriagesWeight'],stock['wheelsDiameter'],stock['frontSurface'],stock['driveAxles'],stock['pistonsLength'],stock['cylinders'],stock['expansion'],stock['k'],self.cylinderDiameter,self.startingPhase)+aGauss()
          self.a=live[0]
#          self.vapor=live[1]
#          self.coal=live[2]
        if not __debug__:
          print self.name+":t:"+str(t)+":REACTION, a:"+str(self.a)
        self.waitReact=0.0
    if (self.v<=0.0):
      self.startingPhase=True
    elif (self.v>2.5):
      self.startingPhase=False
#
# STAGE 6 : switches segment after passing a 4D sig
#
    if (self.initSwitchSeg==True):
      self.initSwitchSeg=False
#      print "calling SWITCH "+self.name
      self.switch(self.name,self.pathBranch,deltaX)
    if removeTr==True:
      return self
    else:
      return None

def aGauss():
  return random.gauss(0.0,ACCSIGMA)

def findMyCRVcnt(x,seg):
  global crvs
  xK=x/1000.0
  cnt=0
  for ast in crvs[seg]:
    if float(ast[0])>=xK:
      if cnt>0:
        return (cnt-1)
      else:
        return cnt
    cnt=cnt+1
  return cnt-1

def findMyGRDcnt(x,seg):
  global grds
  xK=x/1000.0
  cnt=0
  for ast in grds[seg]:
    if float(ast[0])>=xK:
      if cnt>0:
        return (cnt-1)
      else:
        return cnt
    cnt=cnt+1
  return cnt-1

def findMySTAcnt(x,seg):
  global stas
  xK=x/1000.0
  cnt=0
  found=False
  for ast in stas[seg]:
    if float(ast[0])>=xK:
      break
    cnt=cnt+1
  return cnt

def findMySIGcnt(x,seg):
  global sigs
  xK=x/1000.0
  cnt=0
  found=False
  for asi in sigs[seg]:
    if float(asi[0])>=xK:
      break
    cnt=cnt+1
  return cnt

def attemptLock4C(aSig,name):  # aSig is a type 6
  convSig=findSuccSig(aSig)
  if not __debug__:
    print str(name)+":in attemptLock4C, convSig:"+str(convSig)
  if 'type' in convSig:
    convPeerSig=getSigPeer(convSig)
#    print "in attemptLock4C, convPeerSig:"+str(convPeerSig)
    redisConvSIG="sig:"+convSig['seg']+":"+sigs[convSig['seg']][convSig['cnt']][1]
    redisConvPeerSIG="sig:"+convPeerSig['seg']+":"+sigs[convPeerSig['seg']][convPeerSig['cnt']][1]
    convAlreadyOccupied=r.get(redisConvSIG+":isOccupied") 
    if convAlreadyOccupied is not None:
      if convAlreadyOccupied!=name:
        return False
  #  kConv=r.get(redisConvSIG)
  #  kConvPeer=r.get(redisConvPeerSIG)
    convAlreadyLocked=r.get(redisConvSIG+":isLocked") 
    convPeerAlreadyLocked=r.get(redisConvPeerSIG+":isLocked")
    if (convAlreadyLocked!=convPeerAlreadyLocked):
      print "FATAL isLocked inconsistency..."+str(convAlreadyLocked)+" "+str(convPeerAlreadyLocked)+" "+redisConvSIG+" "+redisConvPeerSIG
      sys.exit()
    if convAlreadyLocked is None:
      r.set(redisConvSIG+":isLocked",name) 
      r.set(redisConvPeerSIG+":isLocked",name) 
      peerSig=getSigPeer(aSig)
      redisPeerSIG="sig:"+peerSig['seg']+":"+sigs[peerSig['seg']][peerSig['cnt']][1]
      if (r.get(redisPeerSIG)=="green"):
        r.set(redisPeerSIG,"yellow")
      if (r.get(redisConvSIG)=="red"):
        r.set(redisConvSIG,"yellow")   
      if (r.get(redisConvPeerSIG)!="red"):
        r.set(redisConvPeerSIG,"red")   
      return True
    else:
      return (convAlreadyLocked==name)
  else:
    return False
 
def findSuccSig(aSig):
  global sigs
  succSig={}
  if (aSig['cnt']<len(sigs[aSig['seg']])-1):
    succSig['seg']=aSig['seg']
    succSig['cnt']=aSig['cnt']+1
    succSig['type']=sigs[succSig['seg']][succSig['cnt']][2]
    succSig['name']=sigs[succSig['seg']][succSig['cnt']][1]
  return succSig

def findPrevSig(aSig):
  global sigs
  prevSig={}
  if ((aSig['type']=='1') or (aSig['type']=='6') or (aSig['type']=='2') or (aSig['type']=='3') or (aSig['type']=='4D') or (aSig['type']=='4C')):
    if ((aSig['type']=='2') and (aSig['cnt']==0)):
      print "FATAL ERROR. Service must be reversed before invoking prevSIG"
      sys.exit()
    elif ((aSig['type']=='4D') or (aSig['type']=='4C')):
      kMain=r.get("switch:"+sigs[aSig['seg']][aSig['cnt']][1]+":mainPosition")
      kPrevCnt=int(r.get("switch:"+sigs[aSig['seg']][aSig['cnt']][1]+":mainPrevSig"))
      prevSig['seg']=kMain
      prevSig['cnt']=kPrevCnt
      prevSig['type']=sigs[kMain][kPrevCnt][2]
      prevSig['name']=sigs[kMain][kPrevCnt][1]
      if not __debug__:
        print "this type 4 has a pred "+str(sigs[prevSig['seg']][prevSig['cnt']][1])+" in segment "+str(kMain)
    else:
      prevSig['seg']=aSig['seg']
      prevSig['cnt']=aSig['cnt']-1
      prevSig['type']=sigs[aSig['seg']][prevSig['cnt']][2]
      prevSig['name']=sigs[aSig['seg']][prevSig['cnt']][1]
  elif (aSig['type']=='5'):
    if (sigs[aSig['seg']][aSig['cnt']-1][2]=='2'):
      kRev=r.get("switch:"+sigs[aSig['seg']][aSig['cnt']-1][1]+":reversePosition")
      kFor=r.get("switch:"+sigs[aSig['seg']][aSig['cnt']-1][1]+":forwardPosition")
      kPrevCnt=int(r.get("switch:"+sigs[aSig['seg']][aSig['cnt']-1][1]+":forwardPrevSig"))
      if (aSig['seg']==kRev):
        kOther=kFor
      else:
        kOther=kRev
    if not __debug__:
      print "this type 5 has a type 2 pred "+str(sigs[aSig['seg']][aSig['cnt']-1][1])
      print "this type 2 pred has a type 3 pred "+str(kOther)
    prevSig['seg']=kOther
    prevSig['cnt']=kPrevCnt
    prevSig['type']=sigs[kOther][kPrevCnt][2]
    prevSig['name']=sigs[kOther][kPrevCnt][1]
    if not __debug__:
      print "here is the corresponding type 3: "+str(prevSig)
  if prevSig['cnt']<0:
    prevSig=None
  if not __debug__:
    print "the prec SIG of "+str(aSig)+" is: "+str(prevSig)
  return prevSig

def findMyTIVcnt(x,seg):
  global tivs
  xK=x/1000.0
  cnt=0
  for ati in tivs[seg]:
    if float(ati[0])>=xK:
      if (cnt>0):
        return cnt-1
      else:
        return cnt
    cnt=cnt+1
  return cnt-1

def getSigPeer(aSig):
  global sigs
  sig={}
  if aSig['type']=='4C':
    # determine 4C name in the other leg
    kMain=r.get("switch:"+sigs[aSig['seg']][aSig['cnt']][1]+":mainPosition")
    kBranch=r.get("switch:"+sigs[aSig['seg']][aSig['cnt']][1]+":branchPosition")
    kMainPrevCnt=int(r.get("switch:"+sigs[aSig['seg']][aSig['cnt']][1]+":mainPrevSig"))
    kBranchPrevCnt=int(r.get("switch:"+sigs[aSig['seg']][aSig['cnt']][1]+":branchPrevSig"))
    peerSeg=''
    if kMain==aSig['seg']:
      peerSeg=kBranch
      peerCnt=kBranchPrevCnt
    else:
      peerSeg=kMain
      peerCnt=kMainPrevCnt
    sig['name']=aSig['name']
    sig['seg']=peerSeg
    sig['cnt']=peerCnt+1
    sig['type']=aSig['type']
    peerStr="sig:"+peerSeg+":"+sigs[peerSeg][peerCnt+1][1]
    if not __debug__:
      print str(aSig)+" 4C is the following : "+peerStr+" in branch"+peerSeg
      print str(sig)
  elif aSig['type']=='6':
    # fetch the other 6 via common 4C:
    kMain=r.get("switch:"+sigs[aSig['seg']][aSig['cnt']+1][1]+":mainPosition")
    kBranch=r.get("switch:"+sigs[aSig['seg']][aSig['cnt']+1][1]+":branchPosition")
    kMainPrevCnt=int(r.get("switch:"+sigs[aSig['seg']][aSig['cnt']+1][1]+":mainPrevSig"))
    kBranchPrevCnt=int(r.get("switch:"+sigs[aSig['seg']][aSig['cnt']+1][1]+":branchPrevSig"))
    peerSeg=''
    if kMain==aSig['seg']:
      peerSeg=kBranch
    else:
      peerSeg=kMain
    peerStr="sig:"+peerSeg+":"+sigs[peerSeg][kBranchPrevCnt][1]
    kPeer=r.get(peerStr)
    if not __debug__:
      print str(aSig)+":6 has the following 4C: "+kMain+" "+kBranch
      print "6 has the following peer in other branch mainCnt="+str(kMainPrevCnt)+" branchCnt="+str(kBranchPrevCnt)+" string: "+peerStr+" color="+kPeer
    sig['name']=sigs[peerSeg][kBranchPrevCnt][1]
    sig['seg']=peerSeg
    sig['cnt']=kBranchPrevCnt
    sig['type']=aSig['type']
    if not __debug__:
      print "the peerSig of "+str(aSig)+" is "+str(sig)
  else:
    print "FATAL..."+str(aSig)+" is neither atype 6 nor a type 4C..."
    sys.exit()
  return sig

def updateSIGbyTrOccupationWrapper(aSig,name,state):
  global sigs
  if aSig['type']=='4C':
    sig=getSigPeer(aSig)
    if not __debug__:
      print "sig 4C UPDATE in order:"+str(aSig)+" "+state+","+str(sig)+" "+state
    updateSIGbyTrOccupation(aSig,name,state) #The order is important! First update aSig, then peer sig
    updateSIGbyTrOccupation(sig,name,state)
  elif aSig['type']=='6':
    sig=getSigPeer(aSig)
    peerState=state
    kPeer=r.get("sig:"+sig['seg']+":"+sig['name'])
    if ((kPeer=="green") and (state=="red")):
      peerState="yellow"
    if not __debug__:
      print "sig 6 UPDATE in order:"+str(aSig)+" "+state+","+str(sig)+" "+peerState
    updateSIGbyTrOccupation(aSig,name,state) #The order is important! First update aSig, then peer sig
    updateSIGbyTrOccupation(sig,name,peerState)
  elif aSig['type']=='4D':
    kMain=r.get("switch:"+sigs[aSig['seg']][aSig['cnt']][1]+":mainPosition")
    kBranch=r.get("switch:"+sigs[aSig['seg']][aSig['cnt']][1]+":branchPosition")
    sig1={}
    sig2={}
    sig1['type']=aSig['type']
    sig2['type']=aSig['type']
    sig1['name']=aSig['name']
    sig2['name']=aSig['name']
    sig1['seg']=kMain
    sig2['seg']=kBranch
    kCnt=r.get("switch:"+sigs[aSig['seg']][aSig['cnt']][1]+":mainPrevSig")
    if ((kMain is None) or (kBranch is None) or (kCnt is None)):
      print "FATAL: "+str(aSig)+" is misconfigured..."+str(kMain)+" "+str(kBranch)+" "+str(kCnt)+"..."
      sys.exit()
    kCnt=int(kCnt)
    sig1['cnt']=kCnt+1
    sig2['cnt']=0  #the diverging branch of a 4D always starts a segment
    updateSIGbyTrOccupation(sig1,name,state)
    updateSIGbyTrOccupation(sig2,name,state)
  else:
    updateSIGbyTrOccupation(aSig,name,state)

def updateSIGbyTrOccupation(aSig,name,state):
  global sigs
  convSig={}
  redisSIG="sig:"+aSig['seg']+":"+sigs[aSig['seg']][aSig['cnt']][1]
  k=r.get(redisSIG)
  if not __debug__:
    print name+":"+str(t)+":START UPDATE SIG BY OCCU "+redisSIG+" from value "+k+" to value "+state
  sigAlreadyOccupied=r.get(redisSIG+":isOccupied")
  sigAlreadyLocked=None
  if (aSig['type']=='4C'):
    sigAlreadyLocked=r.get(redisSIG+":isLocked")  # only useful for types 6 and 4C
  elif (aSig['type']=='6'):
    peerSig=getSigPeer(aSig)
    convSig=findSuccSig(aSig)
    convPeerSig=getSigPeer(convSig)
    redisConvSIG="sig:"+convSig['seg']+":"+sigs[convSig['seg']][convSig['cnt']][1]
    redisConvPeerSIG="sig:"+convPeerSig['seg']+":"+sigs[convPeerSig['seg']][convPeerSig['cnt']][1]
    redisPeerSIG="sig:"+peerSig['seg']+":"+sigs[peerSig['seg']][peerSig['cnt']][1]
    kConv=r.get(redisConvSIG)
    kConvPeer=r.get(redisConvPeerSIG)
    kPeer=r.get(redisPeerSIG)
    convAlreadyLocked=r.get(redisConvSIG+":isLocked")  # only useful for types 6 and 4C
    convPeerAlreadyLocked=r.get(redisConvPeerSIG+":isLocked")
    if (convAlreadyLocked!=convPeerAlreadyLocked):
      print "FATAL isLocked inconsistency..."+str(convAlreadyLocked)+" "+str(convPeerAlreadyLocked)+" "+redisConvSIG+" "+redisConvPeerSIG
      sys.exit()
  else:
    convSig={}
    convPeerSig={}
    peerSig={}
    redisConvSIG=""
    redisConvPeerSIG=""  
    redisPeerSIG=""  
    kConv=None
    kConvPeer=None
    kPeer=None
  if (aSig['type']!='0'):
    if (state=="red"):
      if sigAlreadyOccupied is not None:
        if sigAlreadyOccupied!=name:
          print name+":"+str(t)+":FATAL is already occupied "+redisSIG+" by "+sigAlreadyOccupied
          sys.exit()
      r.set(redisSIG+":isOccupied",name)
      if (aSig['type']=='6'):
        if convAlreadyLocked is None:
          r.set(redisConvSIG+":isLocked",name)
          r.set(redisConvPeerSIG+":isLocked",name)
        if (kPeer=="green"):
          r.set(redisPeerSIG,"yellow")
      r.set(redisSIG,state)
#      r.set(redisConvSIG,state)
      sigAlreadyOccupied=name
      previousSig=findPrevSig(aSig)
      if previousSig is not None: 
        redisSIGm1="sig:"+previousSig['seg']+":"+sigs[previousSig['seg']][previousSig['cnt']][1]
        km1=r.get(redisSIGm1+":isOccupied")
        if not __debug__:
          print name+":"+str(t)+":investigating redisSIGm1..."+redisSIGm1+"isOccupied?"+str(km1)
        if km1 is not None:
          if km1==name:
            r.delete(redisSIGm1+":isOccupied")
            updateSIGbyTrOccupationWrapper(previousSig,name,"yellow")
        previousPreviousSig=findPrevSig(previousSig)
        if previousPreviousSig is not None:
          redisSIGm2="sig:"+previousPreviousSig['seg']+":"+sigs[previousPreviousSig['seg']][previousPreviousSig['cnt']][1]
          km2=r.get(redisSIGm2+":isOccupied")
          if not __debug__:
            print name+":"+str(t)+":investigating redisSIGm2..."+redisSIGm2+" isOccupied?"+str(km2)
          if km2 is None:
            if km1 is not None:
              if km1==name:
                updateSIGbyTrOccupationWrapper(previousPreviousSig,name,"green")
            else:
              updateSIGbyTrOccupationWrapper(previousPreviousSig,name,"green")
          elif (km2==name):
            r.delete(redisSIGm2+":isOccupied")
            if km1 is not None:
              if km1==name:
                updateSIGbyTrOccupationWrapper(previousPreviousSig,name,"green")
            else:
              updateSIGbyTrOccupationWrapper(previousPreviousSig,name,"green")
    elif (state=="yellow"):
      if sigAlreadyOccupied is not None:
        if sigAlreadyOccupied==name:
          r.delete(redisSIG+":isOccupied")
      previousSig=findPrevSig(aSig)
      if previousSig is not None:
        redisSIGm1="sig:"+previousSig['seg']+":"+sigs[previousSig['seg']][previousSig['cnt']][1]
        km1=r.get(redisSIGm1+":isOccupied")
        if km1 is None:
          updateSIGbyTrOccupationWrapper(previousSig,name,"green")
        else:
          if km1==name:
            r.delete(redisSIGm1+":isOccupied")
            updateSIGbyTrOccupationWrapper(previousSig,name,"green")
    elif (state=="green"):
      if sigAlreadyOccupied is not None:
        if sigAlreadyOccupied==name:
          r.delete(redisSIG+":isOccupied")
      if (aSig['type']=='6'):
        if sigAlreadyLocked is not None:
          if sigAlreadyLocked==name:
            r.delete(redisConvSIG+":isLocked")
            r.delete(redisConvPeerSIG+":isLocked")
    if not __debug__:
      print "SIGCHG "+str(aSig)+" was "+k+" now "+state
  if (aSig['type']!='2'):   # a type 2 always remains red
    r.set(redisSIG,state)

def getAccForEMU(po,refAcc,railF,airF,vK,m):
  global stock
  f=0.07*m*G*(railF+airF*vK*vK/12.96)
  powerFromFactors=vK*f/3.6
  availablePower=po-powerFromFactors
  if (availablePower<0.0):
    return 0.0
  if (vK>0.0):
    acc=3.6*availablePower/(m*vK)
    return min(acc,refAcc)
  else:
    return refAcc

def scheduler(period,f,*args):
  def g_tick():
    t1 = time.time()
    count = 0
    while True:
      count += 1
      yield max(t1 + count*period - time.time(),0)
  g = g_tick()
  while True:
    time.sleep(next(g))
    f(*args)

def stepRT(s):
  global ncyc
  global trs
  global exitCondition
  global t
  global cycles
  global live
  global remlist
  global r
  global simID
  global version
  global minVersion
  global schedOrders
  ccc=0
  t=ncyc/CYCLE
  if (t>duration):
    exitCondition=True
    print "EXIT condition True"
    sys.exit()
  intT=int(t)
  r.set("elapsed",t)
  r.set("elapsedHuman",str(datetime.timedelta(seconds=intT)))
  if not __debug__:
    print "RT:"+str(t)
  if (intT%6==0):
    checkOrders()
    sys.stdout.flush()
    if ((intT>0) and (intT%900==0)): 
      glo={}
      glo['simID']=simID
      glo['t']=t
      glo['ncyc']=ncyc
      glo['route']=projectDir
      glo['schedule']=scheduleName
      glo['schedOrders']=schedOrders
      glo['version']=version
      pickName='saves/'+simID+"."+str(intT)+".trains"
      pickle.dump(trs,open(pickName,"wb"))
      pickName='saves/'+simID+"."+str(intT)+".globals"
      pickle.dump(glo,open(pickName,"wb"))
      r.save()
  if len(remlist)>0:
    newlist=[]
    for tr in trs:
      found=False
      for rm in remlist:
        if rm.name==tr.name:
          found=True
          #state=r.hgetall('state:'+rm.name)
          for key in r.scan_iter('state:'+rm.name):
            r.delete(key)
          p={}
          p['seg']=rm.segment
          p['cnt']=rm.SIGcnt
          p['type']=sigs[rm.segment][rm.SIGcnt][2]
          previousSig=findPrevSig(p)
          if previousSig is None:
            print "FATAL: no previousSig"
            sys.exit()
          previousPreviousSig=findPrevSig(previousSig)
          updateSIGbyTrOccupationWrapper(p,rm.name,"green")
          updateSIGbyTrOccupationWrapper(previousSig,rm.name,"green")
          if previousPreviousSig is not None:
            updateSIGbyTrOccupationWrapper(previousPreviousSig,rm.name,"green")
      if found==False:
        newlist.append(tr)
    trs=newlist
    if len(trs)<1:
      print str(t)+":INFO: Simulation ended. All services have run their schedule. Bye Bye!"
      sys.exit(1)
  remlist=[]
  while (ccc<cycles):
    t=ncyc/CYCLE
#    r.set("elapsed",int(t))
#    r.set("elapsedHuman",str(datetime.timedelta(seconds=int(t))))
#    if not __debug__:
#      print "RT:"+str(t)
    for aT in trs:
      rem=aT.step() 
      if rem is not None:
        if not __debug__:
          print "Removing Tr "+str(aT.name)
        remlist.append(rem)
    ncyc=ncyc+1
    ccc=ccc+1
  for aT in trs:
    aT.dumpstate()
  time.sleep(.3)

def longTail(startpoint,incr,maxval):
    if (startpoint<1.0):
      return -2 # not fat enough!
    returnval=1
    point=startpoint
    h=random.uniform(0.0,1.0)
    while True:
      if (returnval>maxval):
        return maxval #retry with another thincounter
      if (h<(1/point)):
        point=point+incr
        returnval=returnval+1
      else:
        return min(maxval,float(returnval)*random.uniform(0.71,1.63))

def strahl(Vk,VVk,m,k,starting):   # rolling resistance (in Newton) of train carriages (excluding the locomotive and tender if any)
  # VVK windspeed in kmh (0 to 20)
  # k=0.25 express pax/heavy goods
  # k=0.33 usual pax
  # k=1.0 empty goods
  # k=0.5 misc goods
  # m : poids (t) de la remorque
  V=(Vk+VVk)
  F=(2.5+k*V*V*0.001)*m*G  # 2.5kg/t resistance au roulement en marche
  if ((Vk<2.5) and (starting==True)):
    F=F+15.0*m*G   # Force d arrachement, entre 15kg/t et 20kg/t
  return F

# tractive effort = tractive force
def locoNrollingResistance(Vk,n,m): # n essieux
  # m : poids (kg) du train
  F=(0.00065+(13*n/m)+0.000036*Vk+0.00039*Vk*Vk/m)*m*G
  if (Vk<1.0):
    F=F+0.0075*m*G   # Force d arrachement, environ 7.5kg/t
  return F

def sanzin(p,P,Vk,Dm,S,ea):  # ea = nb essieux accouples
  # m : poids (t) du train
  # p : poids essieux porteurs (t) y compris tender
  # P : poids essieux moteurs (t)
  a=0.0
  b=0.0
  if (ea==2):
    a=5.5
    b=0.08
  elif (ea==3):
    a=7.0
    b=0.10
  elif (ea==4):
    a=8.0
    b=0.28
  elif (ea==5):
    a=8.8
    b=0.36 
  F=p*(1.8+0.015*Vk)+P*(a+(b/Dm)*Vk)+0.006*S*Vk*Vk
  return F*G

def gradeResistance(p,P,m,i,c):
  #p : poids (t) essieux porteurs y compris tender
  #P : poids (t) essieux moteurs
  #m : poids (t) de la remorque
  #i : grade (in mm/m)
  #c : curve (in m)
  F=(m+p+P)*(i+(750.0/c))
  return F*G

def rollingResistance(p,P,m,i,c,Vk,VVk,Dm,S,ea,k,starting):
  # resistance de tout le train (remorque+loco+tender)
  return gradeResistance(p,P,m,i,c)+sanzin(p,P,Vk,Dm,S,ea)+strahl(Vk,VVk,m,k,starting)

def indicatedPowerInHorsePower(r,Vk):
  # r: rollingresistance
  return r*Vk/(G*270.0)

def hourlyVaporConsumptionInKg(iP,Pr,tp):
  # Pr: pressure (timbre) in kg/cm2 between 12.0 and 25.0
  # iP: indicatedPowerInHorsePower
  if tp=='simpleExpansion':
    return iP*(7.0-(Pr-12.0)*0.092)
  elif tp=='compound':
    return iP*(6.8-(Pr-12.0)*0.092)

def hourlyCoalConsumptionInKg(vC):
  # vC: hourlyVaporConsumptionInKg
  # 1kg of coal produces 8kg of vapor
  return vC/8.0

def gridSurfaceInM2(hC,a,b):
  # a: between 57.0 to 70.0, the latest is hard on the chaudiere. reco : 65.0
  # b: between 50.0 and 70.0 Reco : 50.0
  S=hC/a   # surface de chauffe vaporisante
  Gr=S/b  
  return Gr

def locoWeightInTons(hC,a):
  # a : same as grdSurfaceInM2. Reco 65.0
  # result without coal and water. Add 9t for that!
  return 0.5*hC/a

def cylinderPressureInKgCm2(Pr,tp):
  # Pr: pressure (timbre) in kg/cm2 between 12.0 and 25.0
  if tp=='simpleExpansion':
#    return 3.6+(Pr-12.0)*0.11
    return 4.14+(Pr-12.0)*0.11
  elif tp=='compound':
#    return 3.4+(Pr-12.0)*0.11
    return 3.94+(Pr-12.0)*0.11

def cylinderDiameterInCm(n,r,Dm,cP,l):
  # r:rolling resistance
  # cP : cylinderPressurInKgCm2
  # piston course in m
  # n: nb of cylinders
  return math.pow(((r/G)*Dm*2)/(cP*l*n),0.5)

def tractiveEffortAtStart(Pr,d,l,Dm,n,tp):
  # Pr : timbre in kg/cm2
  # d : cylinder diam in Cm
  # l : piston course
  # n : number of cylinders
  if tp=='simpleExpansion':
    return n*G*0.75*Pr*d*d*l/(2.0*Dm)

def checkAdherence(tra,P):
  # P: poids (t) essieux accouples
  # tra : tractiveeffortatstart
  # f : coeff adherence
  # if False, need to increase ea (number of essieux accouples) or poids par essieux (depends on railroad specs) or reduce cylinders volume or number of cylinders
  return (P*1000.0*ADHESIVEFACTOR)>(tra/G)

def getLiveDataForSTM(vK,vvK,grd,curv,critVk,maxVk,timbre,locoW,tenderW,payloadW,Dm,Sm2,ea,l,nCyl,exp,k,d,starting):
  global live
  localCurv=abs(float(curv))
  if localCurv==0.0:
    localCurv=99999999.9 
#  r=rollingResistance(locoW/1000.0,tenderW/1000.0,payloadW/1000.0,grd,localCurv,vK,0.0,Dm,Sm2,ea,k,True)
#  cP=cylinderPressureInKgCm2(timbre,exp)
# d=cylinderDiameterInCm(nCyl,r,Dm,cP,l)
#    print r
#    print rollingResistance(99.0,48.0,250.0,2.0,1000.0,110.0,0.0,1.90,10.0,2,0.25,True)
#    cP=cylinderPressureInKgCm2(stock['timbre'],stock['expansion'])
#    d=cylinderDiameterInCm(stock['cylinders'],r,stock['wheelsDiameter'],cP,stock['pistonsLength'])

  vMaxReached=False
  acc=0.0
  tEff=0.0
  rLTremorque=strahl(vK,vvK,payloadW/1000.0,k,starting)+sanzin(locoW/1000.0,tenderW/1000.0,vK,Dm,Sm2,ea)
  if (vK<=critVk):
    tEff=tractiveEffortAtStart(timbre,d,l,Dm,nCyl,exp)
  else:
    tEff=tractiveEffortAtStart(timbre,d,l,Dm,nCyl,exp)*critVk/vK
  acc=(tEff-rLTremorque)/(payloadW+locoW+tenderW)
  live=[]
  live.append(acc)
#  live.append(hV)
#  live.append(hC)
  return True

def plot(law):
  global stock
  print "v,r,F,a"
  v=0.0
  vMaxReached=False
  if law=='STM1':
    print stock
    locoW=(stock['driveAxleLoad']*stock['driveAxles']+stock['deadRearAxleLoad']*stock['deadRearAxles']+stock['deadFrontAxleLoad']*stock['deadFrontAxles'])/1000.0
    tenderW=(stock['tenderAxles']*stock['tenderAxleLoad'])/1000.0
    payloadW=(stock['carriagesWeight'])/1000.0
    r=rollingResistance(locoW,tenderW,payloadW,stock['indicatedGrade'],stock['indicatedCurve'],stock['maxSpeed'],0.0,stock['wheelsDiameter'],stock['frontSurface'],stock['driveAxles'],stock['k'],True)
    print str(locoW)+","+str(tenderW)+","+str(payloadW)+","+str(stock['indicatedGrade'])+","+str(stock['indicatedCurve'])+","+str(stock['maxSpeed'])
    print "locoW:"+str(locoW)+" tenderW:"+str(tenderW)+" payloadW:"+str(payloadW)
#    print r
#    print rollingResistance(99.0,48.0,250.0,2.0,1000.0,110.0,0.0,1.90,10.0,2,0.25,True)
    cP=cylinderPressureInKgCm2(stock['timbre'],stock['expansion'])
    d=cylinderDiameterInCm(stock['cylinders'],r,stock['wheelsDiameter'],cP,stock['pistonsLength'])
    criticalSpeed=stock['criticalSpeed']
    tra=tractiveEffortAtStart(stock['timbre'],d,stock['pistonsLength'],stock['wheelsDiameter'],stock['cylinders'],stock['expansion'])
    if checkAdherence(tra,stock['driveAxleLoad']*stock['driveAxles'])==False:
      print "FATAL: adherence failed."
      sys.exit()
    while vMaxReached==False:
      rLTremorque=strahl(v,0.0,payloadW,stock['k'],True)+sanzin(locoW,tenderW,v,stock['wheelsDiameter'],stock['frontSurface'],stock['driveAxles'])
      if (v<=criticalSpeed):
        tEff=tra
      else:
        tEff=tra*criticalSpeed/v
      acc=(tEff-rLTremorque)/(1000.0*(payloadW+locoW+tenderW))
      if (acc<=0.0):
        acc=0.0
      else: 
        print str(v)+","+str(rLTremorque)+","+str(tEff)+","+str(acc)
      if tEff<=rLTremorque:
        vMaxReached=True
      v=v+0.25
  elif law=='EMU1':
    m=stock['weight']+MAXPAX*PAXWEIGHT
    while vMaxReached==False:
      f=0.07*m*G*(stock['railFactor']+stock['airFactor']*v*v/12.96)
      powerFromFactors=v*f/3.6
      availablePower=stock['power']-powerFromFactors
      if (availablePower<0.0):
        print str(v)+",0.0"
        vMaxReached=True
      if (v>0.0):
        acc=3.6*availablePower/(m*v)
        print str(v)+","+str(min(acc,stock['acceleration']))+","+str(powerFromFactors)
      else:
        print str(v)+","+str(stock['acceleration'])+","+str(powerFromFactors)
      v=v+0.25
  
def sim():
  global cycles
  global executor
  global trs
  global t
  global exitCondition
  global ncyc
  global remlist
  global r
  for aT in trs:
    if not __debug__:
      print aT.name+" has been initialized"
#  if (DUMPDATA==True):
#    if (TPROGRESS==True):
#      print "service,trip,t,x,v,a,P"
#    if (STAPROGRESS==True):
#      print "service,trip,time,station"

  if (realTime==True):
    cycles=CYCLEPP
    executor.submit(scheduler,SYNCPERIOD,stepRT,'none')
    return "started realtime sim"
  else:
    cycles=CYCLE
    #noRT()
    executor.submit(noRT)
    return "started accelerated sim"

def simSave():
  global saveOrder
  global r
  global t
  global simID
  global ncyc
  global schedOrders
  global minVersion
  global version
  pickName='saves/'+saveOrder['name']+".trains"
  pickle.dump(trs,open(pickName,"wb"))
  glo={}
  glo['time']=t
  glo['simID']=simID
  glo['ncyc']=ncyc
  glo['route']=projectDir
  glo['schedule']=scheduleName
  glo['schedOrders']=schedOrders
  glo['version']=version
  r.save()
  pickName='saves/'+saveOrder['name']+".globals"
  pickle.dump(glo,open(pickName,"wb"))
  saveOrder={}
  return True

def checkOrders():
  global schedOrders
  global saveOrder
  global t
  global trs
  if 'time' in saveOrder:
    if saveOrder['time']<=int(t): 
      simSave()
  if len(schedOrders)>0:
    for s in schedOrders:
      if 'time' in s:
        if int(s['time'])<=int(t):
          if s['service']=='UPDATE':
            found=False
            for aT in trs:
              if aT.name==s['name']:
                print "<<<<"+aT.name
                if aT.service is None:
                  item=s['sigName']+':'+s['sigDir']
                  aT.service=[]
                  aT.service.append(item)
                  print aT.service
                for asv in aT.service:
                  asp=asv.split(":") 
                  print asv
                  print "asp:"+str(asp)+" asp0:"+str(asp[0])
                  if asp[0]==s['sigName']:
                    asp[1]=s['sigDir']
                  print asv
    schedOrders[:]=[s for s in schedOrders if (s['service']!='UPDATE')] 
  return True

def noRT():
  global cycles
  global executor
  global trs
  global t
  global exitCondition
  global ncyc
  global remlist
  global r 
  global simID
  global minVersion
  global version
  global schedOrders
  while (exitCondition==False):
    t=ncyc/CYCLE
    intT=int(t)
    r.set("elapsed",t)
    r.set("elapsedHuman",str(datetime.timedelta(seconds=intT)))
    if (intT%6==0):
      sys.stdout.flush()
      checkOrders()
      if ((intT>0) and (intT%SAVEFREQ==0)):
        pickName='saves/'+simID+"."+str(intT)+".trains"
        pickle.dump(trs,open(pickName,"wb"))
        pickName='saves/'+simID+"."+str(intT)+".globals"
        glo={}
        glo['simID']=simID
        glo['time']=t
        glo['ncyc']=ncyc
        glo['route']=projectDir
        glo['schedule']=scheduleName
        glo['schedOrders']=schedOrders
        glo['version']=version
        pickle.dump(glo,open(pickName,"wb"))
        r.save()
    for aT in trs:
      rem=aT.step()
      if rem is not None:
        if not __debug__:
          print "Removing Tr "+str(aT.name)
        remlist.append(rem)
    if len(remlist)>0:
      newlist=[]
      for tr in trs:
        found=False
        for rm in remlist:
          if rm.name==tr.name:
            found=True
            #state=r.hgetall('state:'+rm.name)
            for key in r.scan_iter('state:'+rm.name):
              r.delete(key)
            p={}
            p['seg']=rm.segment
            p['cnt']=rm.SIGcnt
            p['type']=sigs[rm.segment][rm.SIGcnt][2]
            previousSig=findPrevSig(p)
            if previousSig is None:
              print "FATAL: no previousSig"
              sys.exit()
            previousPreviousSig=findPrevSig(previousSig)
            updateSIGbyTrOccupationWrapper(p,rm.name,"green")
            updateSIGbyTrOccupationWrapper(previousSig,rm.name,"green")
            if previousPreviousSig is not None:
              updateSIGbyTrOccupationWrapper(previousPreviousSig,rm.name,"green")
        if found==False:
          newlist.append(tr)
      trs=newlist
      if len(trs)<1:
        print str(t)+":INFO: Simulation ended. All services have run their schedule. Bye Bye!"
        sys.exit(1)
    remlist=[]
    if (t>duration):
      exitCondition=True
    ncyc=ncyc+1

executor=ThreadPoolExecutor(max_workers=5)
app=flask.Flask(__name__)

@app.route("/v1/describe/status", methods=["GET"])
def v1status():
  global t 
  global simID
  global realTime
  global projectDir
  global routeName
  status={}
  status['t']=t
  status['simID']=simID
  status['realTime']=realTime
  status['routeName']=routeName
  return json.dumps(str(status))

@app.route("/v1/save/<sname>/<tm>", methods=["POST","GET"])
def v1simsave(sname,tm):
  global saveOrder
  saveOrder['name']=sname
  saveOrder['time']=int(tm)
  return '[]'

@app.route("/v1/update/schedule/<sc>/<signame>/<sigdir>/<tm>", methods=["POST","GET"])
def v1updatechedule(sc,signame,sigdir,tm):
  global schedOrders
  found=False
  for so in schedOrders:
    if so['name']==sc:
      so['service']='UPDATE'
      so['sigDir']=sigdir
      so['sigName']=signame
      so['time']=int(tm)
      so['id']=str(uuid.uuid4())
      found=True   # there must be only one order per schedule => overriding the previous one
      return json.dumps(so['id']) 
  found=False
  for t in trs:
    if t.name==sc:
      found=True
      break
  if found==False:
    return '[]'
  else:
    so={}
    so['name']=sc
    so['service']='UPDATE'
    so['sigDir']=sigdir
    so['sigName']=signame
    so['time']=float(tm)
    so['id']=str(uuid.uuid4())
    schedOrders.append(so)
  return json.dumps(so['id'])

@app.route("/v1/new/schedule/<sc>/<srv>/<tm>", methods=["POST","GET"])
def v1newschedule(sc,srv,tm):
  global schedOrders
  found=False
  for so in schedOrders:
    if so['name']==sc:
      newso={}
      newso['name']=sc
      newso['service']=srv
      newso['time']=int(tm)
      newso['id']=str(uuid.uuid4())
      found=True   # there must be only one order per schedule => overriding the previous one
      break
  if found==False:
    so={}
    so['name']=sc
    so['service']=srv
    so['time']=int(tm)
    so['id']=str(uuid.uuid4())
    schedOrders.append(so)
  else:
    schedOrders.remove(so)
    schedOrders.append(newso)
    return json.dumps(newso['id'])
  return json.dumps(so['id'])

@app.route("/v1/list/schedule/orders", methods=["GET"])
def v1listschedorders():
  global schedOrders 
  return json.dumps(schedOrders) 

@app.route("/v1/list/schedules", methods=["GET"])
def v1listschedules():
  global trs 
  retObj=[]
  for aT in trs:
    retObj.append(aT.name) 
  return json.dumps(retObj) 

@app.route("/v1/describe/schedule/<sc>", methods=["GET"])
def v1describeschedule(sc):
  global trs 
  global t
  retItem={}
  for aT in trs:
    if aT.name==sc:
      retItem['name']=aT.name
      retItem['time']=t
      retItem['vK']=aT.vK
      retItem['PK']=aT.PK
      retItem['a']=aT.a
      retItem['segment']=aT.segment
      retItem['isInStation']=aT.inSta
      retItem['isAtSignal']=aT.atSig
      retItem['aheadStation']=aT.nextSTA
      retItem['aheadSignal']=aT.nextSIG
      retItem['service']=aT.service
      retItem['brakeWear']=aT.brakeWear
      retItem['admissionWear']=aT.admissionWear
      retItem['mechanicalWear']=aT.mechWear
      retItem['consumptionCutOff']=aT.consumptionCutOff
      retItem['gFactor']=G*aT.gradient
      break
  return json.dumps(retItem)

try:
  opts, args = getopt.getopt(sys.argv[1:], "h:m", ["help", "plot", "realtime", "core=","duration=", "route=", "schedule=", "services=", "instance=", "resume="])
except getopt.GetoptError as err:
  print(err)
  usage()
  sys.exit(2)
duration = sys.maxsize 
realTime=REALTIME
core=1
scheduleName="default.txt"
stockName="rollingStock.txt"
plotCurves=False
loadSim=False
loadName=''
foundRte=False

serviceList=[]
for o, a in opts:
  if o in ("-h", "--help"):
    usage()
    sys.exit()
  elif o in ("--duration"):
    duration = abs(int(a))
  elif o in ("--realtime"):
    realTime=True
  elif o in ("--plot"):
    plotCurves=True
  elif o in ("--core"):
    core = int(a)
  elif o in ("--route"):
    projectDir = a+'/'
    routeName=a
    foundRte=True
  elif o in ("--instance"):
    redisDB = int(a)
  elif o in ("--resume"):
    loadName = a
    loadSim=True
  elif o in ("--schedule"):
    scheduleName = a
  elif o in ("--services"):
    serviceList = a.split(',')
    print serviceList
    sys.exit()
  else:
    assert False, "option unknown"
    sys.exit(2)

if foundRte==False:
  print "FATAL: route name missing."
  sys.exit()

r=redis.StrictRedis(host='localhost', port=6379, db=redisDB)
try:
  answ=r.client_list()
except redis.ConnectionError:
  print "FATAL: cannot connect to redis."
  sys.exit()

if plotCurves==False:
  r.flushdb()
  r.set("routeName",routeName)
  if loadSim==True:
    pickName='saves/'+loadName+'.globals'
    glo=pickle.load(open(pickName,"rb"))
    t=glo['time']
    simID=glo['simID']
    ncyc=glo['ncyc']
    projectDir=glo['route']
    scheduleName=glo['schedule']
    schedOrders=glo['schedOrders']
    if glo['version']<minVersion:
      print "FATAL: saved version incompatible with current engine."
      sys.exit()
    initAll()
    pickName='saves/'+loadName+'.trains'
    trs=pickle.load(open(pickName,"rb"))
    r.set('elapsed',t)
    r.set('simID',simID)
    for aT in trs:
      aT.dumpstate()
  else:
    initAll()
    simID=str(uuid.uuid4())
    r.set('simID',simID)
  sid={}
  sid['simID']=simID
  print json.dumps(sid) 
  sim()
  if __name__=="__main__":
    app.run(host='127.0.0.1',port=4999,threaded=True)
else:
  initAll()
  r.flushdb()
  r.set("routeName",routeName)
  plot(stock['accelerationLaw'])

#print strahl(110.0,0.0,250.0,0.25,True)
#print sanzin(99.0,48.0,110.0,1.90,10.0,2)
#print gradeR(99.0,48.0,250.0,2.0,1000.0)
#print rollingResistance(p,P,m,i,c,Vk,VVk,Dm,S,ea,k)

#r=rollingResistance(99.0,48.0,250.0,8.0,999999999.9,80.0,0.0,1.90,10.0,2,0.25,True)
#iP=indicatedPowerInHorsePower(r,80.0)
#print iP
#r=rollingResistance(99.0,48.0,250.0,2.0,1000.0,110.0,0.0,1.90,10.0,2,0.25,True)
#iP=indicatedPowerInHorsePower(r,110.0)
#print iP
#print "***"

#hC=hourlyVaporConsumptionInKg(iP,18.0,'simpleExpansion')
#print hC
#print gridSurfaceInM2(hC,65.0,50.0)
#cP=cylinderPressureInKgCm2(18.0,'simpleExpansion')
#print cP
#cylinderDiameter(r,Dm,cP,l)
#d=cylinderDiameterInCm(r,1.90,cP,0.72)
#tractiveEffortAtStart(Pr,d,l,Dm,n,tp)
#tra=tractiveEffortAtStart(18.0,d,0.72,1.90,2,'simpleExpansion')
#print tra
#checkAdherence(tra,P)
#print checkAdherence(tra,48.0)
#print locoWeightInTons(hC,65.0)
print "No more tasks to perform. Bye bye!"
