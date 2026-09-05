# -*- coding: utf-8 -*-
"""
Created on Wed Nov 22 21:50:44 2017

@author: Sujay
"""

import mechanize 
from bs4 import BeautifulSoup as bs
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import numpy as np


class NseData:
    StockName = 'None'
    HistoricalData = []
    KeyWords = []

    def __init__(self, stock_name):
        self.StockName = stock_name
    
    #Gets HIsatorical data of past one year for the given stock
    def GetHistoricalData(self):
        url = "https://www.nseindia.com/products/content/equities/equities/eq_security.htm"
        br = mechanize.Browser()
        br.addheaders = [('User-agent', 'Mozilla/5.0 (X11; U; Linux i686; en-US; rv:1.9.0.1) Gecko/2008071615 Fedora/3.0.1-1.fc9 Firefox/3.0.1')]
        br.set_handle_refresh(False)
        br.set_handle_robots(False)
        br.open(url)
        br.form  = list(br.forms())[0]
        
        #print br.form
        Datatype = br.form.find_control("dataType")
        Symbol = br.form.find_control("symbol")
        Series =  br.form.find_control("series")
        Period = br.form.find_control("dateRange")
               
        CurrentSyymbol = self.StockName
        Datatype.value = ['priceVolumeDeliverable']
        Symbol.value = CurrentSyymbol
        Series.value = ['ALL']
        
        Period.value=['12month']
        #fromDate.value = '22-10-2017'
        #toDate.value = '22-11-2017'
       
    
        response = br.submit()
        result = response.read()
        soup = bs(result, 'lxml')
        HistoricalData = soup.find("div",{"id": "csvContentDiv"})
        
        HistoricalData = str(HistoricalData)
        #print HistoricalData
        #remove div tag
        HistoricalData = HistoricalData[HistoricalData.find('>')+1:]
        HistoricalData = HistoricalData[:HistoricalData.find(":</div>")]
        
        #remove all "
        HistoricalData = "".join(HistoricalData.split())
        HistoricalData = HistoricalData.replace('"', "")
        
        #Make lists
        HDList  = HistoricalData.split(':')
        
        #get Keyword list
        self.KeyWords = HDList[0].split(',')
        #remove the first list, as it is keyword list        
        HDList = HDList[1:]      
        for i in HDList:
            self.HistoricalData.append(i.split(','))
        #print self.KeyWords
        #print self.HistoricalData[1]
    
    #Gets data list of a given keyword
    def GetHistoricalDataList(self, KeyWord):
        DataList =[]
        index = self.KeyWords.index(KeyWord)
        for i in self.HistoricalData:
            if i[self.KeyWords.index("Series")] == "EQ":
                DataList.append(i[index])
        return DataList
    
    #Gets data of a keyword on a given date
    def GetDataOnGivenDate(self, date, KeyWord):
        index = self.KeyWords.index(KeyWord)
        for i in self.HistoricalData:
            if i[self.KeyWords.index("Date")] == date:
                 return i[index]
        return "NONE"
      
    #do aroon indicator calculations
    def Aroon(self, TimeFrame, HighPriceList, LowPriceList):
        AroonUp=[0]*TimeFrame
        AroonDown=[0]*TimeFrame
        #AroonDate=[]
        x=TimeFrame
        
        while (x < len(HighPriceList)):
            Aroon_up = ((HighPriceList[x-TimeFrame:x].index(max(HighPriceList[x-TimeFrame:x]))))/float(TimeFrame)*100
            Aroon_down = ((LowPriceList[x-TimeFrame:x].index(min(LowPriceList[x-TimeFrame:x]))))/float(TimeFrame)*100
            AroonUp.append(Aroon_up)
            AroonDown.append(Aroon_down)                       
            x+=1

        return AroonUp, AroonDown
    

n= NseData('SBIN')
n.GetHistoricalData()
#print n.GetDataOnGivenDate('23-Nov-2017', 'AveragePrice')
hp=n.GetHistoricalDataList("HighPrice")
lp=n.GetHistoricalDataList("LowPrice")
u,l = n.Aroon(14, hp,lp)


#f, (AvgPricePlot, AroonPlot) = plt.subplots(2, sharex=True)
#AvgPricePlot.plot(n.GetHistoricalDataList("AveragePrice"))
#AroonPlot.plot(u)
#AroonPlot.plot(l)


fig = plt.figure(figsize=(8, 6)) 
gs = gridspec.GridSpec(2, 1, height_ratios=[3, 1]) 
AvgPricePlot = plt.subplot(gs[0])
AvgPricePlot.plot(n.GetHistoricalDataList("ClosePrice"))
AroonPlot = plt.subplot(gs[1])
AroonPlot.plot(u)
AroonPlot.plot(l)

#Keywards ['Symbol', 'Series', 'Date', 'PrevClose', 'OpenPrice', 'HighPrice', 'LowPrice', 'LastPrice', 'ClosePrice', 'AveragePrice', 'TotalTradedQuantity', 'Turnover', 'No.ofTrades', 'DeliverableQty', '%DlyQttoTradedQty']
#HistroricalData[1] ['GEECEE', 'EQ', '30-Nov-2016', '128.60', '128.60', '129.75', '124.15', '127.90', '127.40', '126.89', '38211', '4848403.80', '1029', '20556', '53.80']