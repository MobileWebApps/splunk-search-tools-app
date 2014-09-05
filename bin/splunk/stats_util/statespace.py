from optimize import vec
from optimize import dfpmin
from dist import Chisqdist
from dist import Fdist

from itertools import izip
from math import log
from math import exp
from math import sqrt

import time

normality_critical_val = Chisqdist(2).invcdf(.95)


# data: list, k: lag
def autocovariance (data, mean, k):
    """ Compute the k lagged autocovariance of the given data whose mean is passed in"""
    cov = 0.0
    N = len(data)
    if N <= k: return cov
    for i in range(N-k):
        cov += (data[i]-mean)*(data[i+k]-mean)
    return cov/(N-1.) # it's standard pratice in statistics to divide by N-1 instead of N. Also, it's not N-k either (as might be expected).                                                                                                                                  

# data: list
def correlogram (data, n=0):
    """ Compute the correlogram of the given data. The returned correlogram consists of autocorrelations of lag up to n only.
    If n isn't specified, the lag is taken up to len(data)-1. """
    N = len(data)
    mean = float(sum(data))/N
    if n == 0 or n >= N: n = N-1
    var = autocovariance(data,mean,0)
    if var == 0: raise Exception
    yield 1.0
    for i in range(1,n+1):
        yield autocovariance(data,mean,i)/var


# data: a list of float's         
# return -1 if no periodicity is found                                                                                                                                                                       
def findPeriod (data):
    if len(data) == 1: return 1
    cor = correlogram(data)
    try:
        prev = cor.next()
    except Exception:  # this means all elements are equal
        return 1
    curr = cor.next()
    # Go through cor and find the indices of all local peaks.
    # Find the smallest index that might be the period.
    # It's not necessarily the max peak, as the peak at the period may be slightly
    # smaller than the max peak. So we'll ignore the differences that are smaller than 0.01
    peak_idx = 0
    peak_val = 0.0
    for i, next in enumerate(cor):
        if curr > prev and curr > next and curr > peak_val + 0.01:
            peak_val = curr
            peak_idx = i+1
        prev = curr
        curr = next
    if peak_val <= 0.01: return -1
    return peak_idx





FORECAST=3

class LLP3:
    def __init__(self, data, forecast_len=FORECAST):
        if len(data) < self.least_num_data():
            raise ValueError("too few data points: %d" %len(data))

        self.data = data
        self.forecast_len = forecast_len
        self.fc = [None]*(len(data)+forecast_len) # filtered states
        self.p = [None]*len(self.fc) # variances of predictions (not filtered states)

        self.model = self.model1 = LL(data,forecast_len) # starts with LL
        self.period = -1

        for i in range(self.model1.first_forecast_index(),len(self.fc)):
            self.update(i)


    def first_forecast_index(self):
        return self.model1.first_forecast_index()


    def least_num_data(self):
        return LL.least_num_data()

    # User needs to ensure k < len(self.fc)
    def update(self,k):
        data = self.data

        period = findPeriod(data[:k])
        if period != -1 and period != self.period and k > period*LL.least_num_data():
            try:
                self.model2 = LLP(data,period,self.forecast_len)
                self.model = self.model2 
                self.period = self.model2.period
            except ValueError:
                pass

        if self.model.fc[k] != None:
            self.fc[k] = self.model.fc[k]
            self.p[k] = self.model.p[k]
        else:
            self.fc[k] = self.model1.fc[k]
            self.p[k] = self.model1.p[k]


    def variance(self,i):
        if i >= len(self.p): raise ValueError("variance index out of bound")
        return self.p[i]


    def predict(self,length):
        if length <= self.forecast_len: return
        self.model.predict(length)
        oldlen = len(self.fc)
        ext = length - self.forecast_len
        self.fc.extend([None]*ext)
        self.p.extend([None]*ext)
        for i in range(ext):
            self.update(oldlen+i)


        
    def datalen(self):
        return self.model.datalen()


#LLP4 combines LL and LLP
class LLP4:
    def __init__(self, data, forecast_len=FORECAST):
        if len(data) < self.least_num_data():
            raise ValueError("too few data points: %d" %len(data))

        self.data = data
        self.forecast_len = forecast_len
        self.fc = [None]*(len(data)+forecast_len) # filtered states
        self.p = [None]*len(self.fc) # variances of predictions (not filtered states)

        self.model1 = LL(data,forecast_len) # starts with LL
        self.period = -1
        self.model2 = None

        for i in range(self.model1.first_forecast_index(),len(self.fc)):
            self.update(i)


    def first_forecast_index(self):
        return self.model1.first_forecast_index()


    def least_num_data(self):
        return LL.least_num_data()

    # User needs to ensure k < len(self.fc)
    def update(self,k):
        data = self.data

        period = findPeriod(data[:k])
        if period != -1 and period != self.period and k > period*LL.least_num_data():
            try:
                self.model2 = LLP(data,period,self.forecast_len)
                self.period = self.model2.period
            except ValueError:
                pass

        if self.model2 == None or self.model2.p[k]==None or self.model2.fc[k]==None:
            self.p[k] = self.model1.p[k]
            self.fc[k] = self.model1.fc[k]
        elif self.model1.p[k]==0 and self.model2 != None and self.model2.p[k]==0:
            self.p[k] = 0
            self.fc[k] = (self.model1.fc[k]+self.model2.fc[k])/2.
        else:
            K = self.model1.p[k]/(self.model1.p[k]+self.model2.p[k])
            self.fc[k] = self.model1.fc[k] + K*(self.model2.fc[k]-self.model1.fc[k])
            self.p[k] = self.model1.p[k]


    def variance(self,i):
        if i >= len(self.p): raise ValueError("variance index out of bound")
        return self.p[i]


    def predict(self,length):
        if length <= self.forecast_len: return
        self.model1.predict(length)
        self.model2.predict(length)
        oldlen = len(self.fc)
        ext = length - self.forecast_len
        self.fc.extend([None]*ext)
        self.p.extend([None]*ext)
        for i in range(ext):
            self.update(oldlen+i)

        
    def datalen(self):
        return self.model1.datalen()


# LLP5 combines LLT and LLP
class LLP5:
    def __init__(self, data, forecast_len=FORECAST):
        if len(data) < self.least_num_data():
            raise ValueError("too few data points: %d" %len(data))

        self.data = data
        self.forecast_len = forecast_len
        self.fc = [None]*(len(data)+forecast_len) # filtered states
        self.p = [None]*len(self.fc) # variances of predictions (not filtered states)

        self.model1 = LLT(data,forecast_len) # starts with LLT
        self.period = -1
        self.model2 = None

        for i in range(self.model1.first_forecast_index(),len(self.fc)):
            self.update(i)


    def first_forecast_index(self):
        return self.model1.first_forecast_index()


    def least_num_data(self):
        return LL.least_num_data()

    # User needs to ensure k < len(self.fc)
    def update(self,k):
        data = self.data

        period = findPeriod(data[:k])
        if period != -1 and period != self.period and k > period*LL.least_num_data():
            try:
                self.model2 = LLP1(data,period,self.forecast_len)
                self.period = self.model2.period
            except ValueError:
                pass

        if self.model2 == None or self.model2.p[k]==None or self.model2.fc[k]==None:
            self.p[k] = self.model1.p[k]
            self.fc[k] = self.model1.fc[k]
        elif self.model1.p[k]==0 and self.model2 != None and self.model2.p[k]==0:
            self.p[k] = 0
            self.fc[k] = (self.model1.fc[k]+self.model2.fc[k])/2.
        else:
            K = self.model1.p[k]/(self.model1.p[k]+self.model2.p[k])
            self.fc[k] = self.model1.fc[k] + K*(self.model2.fc[k]-self.model1.fc[k])
#            self.p[k] = max(self.model1.p[k],self.model2.p[k])
            self.p[k] = (1-K)*self.model1.p[k]

    def variance(self,i):
        if i >= len(self.p): raise ValueError("variance index out of bound")
        return self.p[i]


    def predict(self,length):
        if length <= self.forecast_len: return
        self.model1.predict(length)
        self.model2.predict(length)
        oldlen = len(self.fc)
        ext = length - self.forecast_len
        self.fc.extend([None]*ext)
        self.p.extend([None]*ext)
        for i in range(ext):
            self.update(oldlen+i)

        
    def datalen(self):
        return self.model1.datalen()



class MIX:
    def __init__(self, model1, model2):
        self.model1 = model1
        self.model2 = model2

        self.fclen = min(len(model1.fc),len(model2.fc))

        self.fc = [None]*self.fclen
        self.p = [None]*self.fclen
        for i in range(self.fclen):
            self.combine(i)


    def combine(self,i):
        [f1,p1,f2,p2] = [None]*4
        
        if i < len(self.model1.p) and self.model1.p[i] != None:
            [f1,p1] = [self.model1.fc[i],self.model1.p[i]]

        if i < len(self.model2.p) and self.model2.p[i] != None:
            [f2,p2] = [self.model2.fc[i],self.model2.p[i]]
        
        if p1==None and p2==None:
            self.fc[i] = self.p[i] = None
        elif p1==None:
            self.fc[i] = f2
            self.p[i] = p2
        elif p2==None:
            self.fc[i] = f1
            self.p[i] = p1
        elif p1==0.:
            self.fc[i] = f1
            self.p[i] = 0.
        elif p2==0.:
            self.fc[i] = f2
            self.p[i] = 0.
        else:
            k = p1/(p1+p2)
            self.fc[i] = f1 + k*(f2-f1)
            self.p[i] = (1-k)*p1



    def first_forecast_index(self):
        return min(self.model1.first_forecast_index(),self.model2.first_forecast_index())


    def least_num_data(self):
        return min(self.model1.least_num_data(),self.model2.least_num_data())


    def variance(self,i):
        if i >= len(self.p): raise ValueError("variance index out of bound")
        return self.p[i]


    def predict(self,length):
        self.model1.predict(length)
        self.model2.predict(length)

        oldlen = len(self.fc)
        self.fc.extend([None]*length)
        self.p.extend([None]*length)
        for i in range(length):
            self.combine(oldlen+i)

        
    def datalen(self):
        return max(self.model1.datalen(),self.model2.datalen())
        

class LL:

    def __init__ (self, data, forecast_len=FORECAST):
        self.data = data
        if len(data) == 0:
            raise ValueError
        n = len(data)
        self.forecast_len = forecast_len
        self.sigma = 0.
        self.nu = 0.
        self.fc = [None]*(n+self.forecast_len) # filtered states
        self.p = [None]*len(self.fc) # variances of predictions (not filtered states)

        idx = self.first_forecast_index()
        self.fc[idx] = self.data[0]
        psi = vec([1.0])
        dfpmin(lambda x: self.llh(exp(x),idx+1), psi)
        self.var = self.p[idx] = exp(psi[0]) + 1.

        if n > idx+1:
            self.update(idx+1)
            self.p[idx] *= self.sigma
            
            for i in range(idx+2,n):
                self.update(i)
                self.var = self.p[n-1]

        # Compute forescast beyond the end of the given data
        # Use equations (2.38) in Durbin-Koopman. Basically, just set v_t = 0 and K_t = 0.
        for i in range(self.forecast_len):
            self.fc[n+i] = self.fc[n-1]
            self.p[n+i] = self.p[n+i-1] + self.nu

        

    @classmethod
    def load(cls,file): # each line consists of a single number
        data = []
        f = open(file,'r')
        data = [float(line.strip()) for line in f]
        f.close()
        cls = LL(data)
        return cls


    @classmethod
    def loadlog(cls,file): # each line consists of a single number
        f = open(file,'r')
        data = [log(float(line.strip())) for line in f]
        f.close()
        cls = LL(data)
        return cls


    @classmethod 
    def least_num_data(cls):
        return 2


    @classmethod
    def first_forecast_index(cls):
        return 1


    def update_kalman (self,y,a,p,q):
        f = p + 1.
        k = p/f
        v = y - a
        a = a + k*v
        p = k + q
        return [a,p,v,f]


    def llh (self,q,k): # compute llh using data up to the k-th data point
        """ The concentrated diffuse loglikelihood. See 'Time Series Analysis by State Space Methods'
        by Durbin-Koopman, p.32."""

        data = self.data[:k]
        a = data[0]
        p = 1.0 + q
        t1, t2 = 0.0, 0.0
        for y in data[1:]:
            [a,p,v,f] = self.update_kalman(y,a,p,q)
            t1 += v**2/f
            t2 += log(f)
        
        if t1 == 0.0: return t2
        return (k-1)*log(t1) + t2


    # optimize paramater q using up to the k-th data point
    # ATTN: k must be AT LEAST 1
    def update(self,k):
        psi = vec([1.0])
        dfpmin(lambda x: self.llh(exp(x),k+1), psi)
        q = exp(psi[0])

        data = self.data[:k+1]
        a = data[0]
        p = 1. + q
        sigma = 0.
        for i in range(1,k):
            [a,p,v,f] = self.update_kalman(data[i],a,p,q)
            sigma += v*v/f
        sigma /= (k-1)
        self.sigma = sigma
        self.nu = q*sigma
        self.fc[k] = a
        self.p[k] = (p+1+q)*sigma 


    def variance(self,i):
        n = len(self.data)
        if i < n:
            return self.p[i]
        else:
            return self.var + (i-n+1)*self.nu
            
    def predict(self,length):
        if length <= self.forecast_len: return 0.0
        nn = len(self.fc)
        ext = length-self.forecast_len
        self.fc.extend([None]*ext)
        self.p.extend([None]*ext)
        for i in range(ext):
            self.fc[nn+i] = self.fc[nn-1]
            self.p[nn+i] = self.p[nn+i-1] + self.nu


    def datalen(self):
        return len(self.data)


class LLE:
    def __init__(self, model):
        self.data = [log(x) for x in model.data]
        classname = model.__class__.__name__
        self.model = globals()[classname](self.data,model.forecast_len)
        self.fc = self.model.fc
#         self.fc = [None]*len(self.model.fc)
#         for i in xrange(len(self.fc)):
#             if self.model.fc[i] != None:
#                 self.fc[i] = exp(self.model.fc[i])
    

    def predict(self,length):
        self.model.predict(length)

    def variance(self,i):
        return self.model.variance(i)

    def datalen(self):
        return self.model.datalen()
    
    def first_forecast_index(self):
        return self.model.first_forecast_index()

    def least_num_data(self):
        return self.model.least_num_data()


class LLP:
    def __init__(self,data,period=-1,forecast_len=FORECAST):
        self.period = period
        if period < 2: 
            self.period = findPeriod(data)
            if self.period == -1: raise ValueError
            
        self.data = data
        self.forecast_len = max(forecast_len,self.period)
        n = len(data)
        if n < self.least_num_data():
            raise ValueError("Too few data points")

        self.models = [None]*self.period
        for i in range(self.period):
            self.models[i] = LL([data[j] for j in range(i,n,self.period)],self.forecast_len/self.period+1)

        self.fc = [None]*(len(data)+self.forecast_len) # filtered states
        self.p = [None]*len(self.fc) # variances of filtered states
        self.e = [None]*len(data) # e = v/sqrt(f) standardised prediction error (Commandeur-Koopman, p. 90)
        
        for i in range(len(self.fc)):
            m = self.models[i%self.period]
            j = i/self.period
            self.fc[i],self.p[i] = m.fc[j],m.p[j]
            
#        self.w = self.period + 1 # 1 superparameter for each sub-model plus 1 for observation noise

        

    @classmethod
    def load(cls,file):
        f = open(file,'r')
        data = [float(line.strip()) for line in f]
        f.close()
        cls = LLP(data,findPeriod(data))
        return cls


    @classmethod
    def loadlog(cls,file):
        f = open(file,'r')
        data = [log(float(line.strip())) for line in f]
        f.close()
        cls = LLP(data,findPeriod(data))
        return cls

    def least_num_data(self):
        return self.period*LL.least_num_data()


    def first_forecast_index(self):
        return self.period*LL.first_forecast_index()

    def variance(self,i):
        return self.models[i%self.period].variance(i/self.period)

    def predict(self,length):
        if length <= self.forecast_len: return 0.0
        period = self.period
        for i in range(period):
            self.models[i].forecast(length)
        nn = len(self.fc)
        ext = length-self.forecast_len
        self.fc.extend([None]*ext)
        self.p.extend([None]*ext)
        for i in range(ext):
            ii = nn+i
            m = self.models[ii%period]
            j = ii/period
            self.fc[ii],self.p[ii] = m.fc[j],m.p[j]

    def datalen(self):
        return len(self.data)

class LLP1:
    def __init__(self,data,period=-1,forecast_len=FORECAST):
        self.period = period
        if period < 2: 
            self.period = findPeriod(data)
            if self.period == -1: raise ValueError
            
        self.data = data
        self.forecast_len = max(forecast_len,self.period)
        n = len(data)
        if n < self.least_num_data():
            raise ValueError("Too few data points")

        self.models = [None]*self.period
        for i in range(self.period):
            self.models[i] = LL([data[j] for j in range(i,n,self.period)],self.forecast_len/self.period+1)

        self.fc = [None]*(len(data)+self.forecast_len) # filtered states
        self.p = [None]*len(self.fc) # variances of filtered states
        self.e = [None]*len(data) # e = v/sqrt(f) standardised prediction error (Commandeur-Koopman, p. 90)


        self.fc[0] = self.models[0].fc[0]
        self.p[0] = self.models[0].p[0]
        for i in range(1,len(self.fc)):
            m = self.models[i%self.period]
            j = i/self.period
            self.fc[i] = m.fc[j]
            self.p[i] = max(self.p[i-1],m.p[j])
            

    @classmethod
    def load(cls,file):
        f = open(file,'r')
        data = [float(line.strip()) for line in f]
        f.close()
        cls = LLP(data,findPeriod(data))
        return cls


    @classmethod
    def loadlog(cls,file):
        f = open(file,'r')
        data = [log(float(line.strip())) for line in f]
        f.close()
        cls = LLP(data,findPeriod(data))
        return cls

    def least_num_data(self):
        return self.period*LL.least_num_data()


    def first_forecast_index(self):
        return self.period*LL.first_forecast_index()

    def variance(self,i):
        return self.p[i]
#        return self.models[i%self.period].variance(i/self.period)

    def predict(self,length):
        if length <= self.forecast_len: return 0.0
        period = self.period
        for i in range(period):
            self.models[i].forecast(length)
        nn = len(self.fc)
        ext = length-self.forecast_len
        self.fc.extend([None]*ext)
        self.p.extend([None]*ext)
        for i in range(ext):
            ii = nn+i
            m = self.models[ii%period]
            j = ii/period
            self.fc[ii] = m.fc[j]
            self.p[i] = max(self.p[i-1],m.p[j])

    def datalen(self):
        return len(self.data)


class LLP2:
    def __init__(self, data, period=-1, forecast_len=FORECAST):
        self.data = data
        self.forecast_len = forecast_len
        self.model1 = LL(data,forecast_len)
        self.model2 = LLP(data,period,forecast_len)
        self.fc = [None]*(len(data)+forecast_len)
        self.p = [None]*len(self.fc)
        for i in range(len(self.fc)):
            self.combine(i)


    def least_num_data(self):
        return min(self.model1.least_num_data(),self.model2.least_num_data())


    def first_forecast_index(self):
        return min(self.model1.first_forecast_index(),self.model2.first_forecast_index())
#        return self.period*LL.first_forecast_index()

    def datalen(self):
        return max(self.model1.datalen(),self.model2.datalen())


    def variance(self,i):
        return self.p[i]

    def predict(self,length):
        if length <= self.forecast_len: return
        
        self.model1.predict(length)
        self.model2.predict(length)

        ext = length-self.forecast_len
        oldlen = len(self.fc)
        self.fc.extend([None]*ext)
        self.p.extend([None]*ext)
        for i in range(ext):
            self.combine(oldlen+i)


    def combine(self,i):
        if self.model1.p[i]==None or self.model1.fc[i]==None:
            self.p[i] = self.model2.p[i]
            self.fc[i] = self.model2.fc[i]
        elif self.model2.p[i]==None or self.model2.fc[i]==None:
            self.p[i] = self.model1.p[i]
            self.fc[i] = self.model1.fc[i]
        elif self.model1.p[i]==0 and self.model2.p[i]==0:
            self.p[i] = 0
            self.fc[i] = (self.model1.fc[i]+self.model2.fc[i])/2.
        else:
            k = self.model1.p[i]/(self.model1.p[i]+self.model2.p[i])
            self.fc[i] = self.model1.fc[i] + k*(self.model2.fc[i]-self.model1.fc[i])
#            self.p[i] = self.model1.p[i]
            self.p[i] = (1-k)*self.model1.p[i]



class LLT:
    """ Local linear trend time series model """
    
    def __init__(self, data, forecast_len=FORECAST):
        if len(data) == 0: raise ValueError
        self.data = data
        self.forecast_len = forecast_len
        self.Z = [1., 0.]
        self.Q = 0.0
        
        self.fc = [None]*(len(data)+self.first_forecast_index()+forecast_len)
        self.p = [None]*len(self.fc)
        self.e = [None]*len(data)
        self.var = 10000.

        first = self.first_forecast_index()
        self.fc[first] = 2*data[1]-data[0]

        psi = vec([1])
        dfpmin(lambda x: -self.llh(exp(x),first+1), psi)
        self.p[first] = exp(psi[0]) #exp(psi[0]/10.)

        self.trend = 0
        self.zeta = 0

        n = len(self.data)
        if n > first+1:
            self.update(first+1)
            self.p[first] *= self.epsilon
            for i in range(first+2,n):
                self.update(i)

        # Compute forescast beyond the end of the given data
        # Use equations (2.38) in Durbin-Koopman. Basically, just set v_t = 0 and K_t = 0.
        for i in range(self.forecast_len):
            self.fc[n+i] = self.fc[n+i-1] + self.trend
            self.p[n+i] = self.p[n+i-1] + self.zeta #+ self.epsilon 
        



    @classmethod
    def load(cls,file): # each line consists of a single number
        data = []
        f = open(file,'r')
        data = [float(line.strip()) for line in f]
        f.close()
        cls = LLT(data)
        return cls


    @classmethod
    def loadlog(cls,file): # each line consists of a single number
        f = open(file,'r')
        data = [log(float(line.strip())) for line in f]
        f.close()
        cls = LLT(data)
        return cls


    @classmethod
    def least_num_data(cls):
        return 2


    @classmethod
    def first_forecast_index(cls):
        return 2


    # Concentrated Kalman filter update
    def update_kalman(self,y,a,P,P2,K,zeta):
        x1 = P[0] + P[2]
        x2 = P[1] + P[3]
        F = P[0] + 1.
        K[0] = x1/F
        K[1] = P[2]/F
        v = y - a[0]
        a[0] = a[0]+a[1]+v*K[0]
        a[1] = a[1]+v*K[1]
        L0 = 1 - K[0]
        # This is not a mistake. This is the transpose of the L in the Kalman formula.
        # We compute the transpose here so we don't need to take the transpose when computing P2 below.
        P2[0] = x1*L0 + x2 + zeta
        P2[1] = x2 - x1*K[1] 
        P2[2] = P[2]*L0 + P[3]
        P2[3] = P[3] - P[2]*K[1]

        return [v,F,log(F)]


    # Steady state update
    def steady_update(self,y,a,K):
        v = y - a[0]
        a[0] = a[0]+a[1]+v*K[0]
        a[1] = a[1]+v*K[1]
        return v


    def next_state(self,data,a,P,P2,K,lF,zeta):
        steady = False
        for y in data:
            if not steady:
                [v,F,lF] = self.update_kalman(y,a,P,P2,K,zeta)
                norm = sum(abs(x-y) for (x,y) in zip(P2,P))
                if norm < 0.001:
                    steady = True
                for i in xrange(4):
                    P[i] = P2[i]
            else:
                v = self.steady_update(y,a,K)
            yield [a,v,F,lF,P]

        

    def llh(self,zeta,datarange=100):
        """ The concentrated diffuse loglikelihood function. """
        data = self.data[self.first_forecast_index():datarange]
        a = [2.*self.data[1]-self.data[0],self.data[1]-self.data[0]]
        P = [5.+2.*zeta,3.+zeta, 3.+zeta,2.+zeta]
        P2 = [None]*4
        F = P[0]+1.0
        lF = log(F)
        K = [(P[0]+P[2])/F, P[2]/F]
        t1, t2 = 0., 0.

        steady = False
        for y in data:
            if not steady:
                [v,F,lF] = self.update_kalman(y,a,P,P2,K,zeta)
                norm = 0
                for i in xrange(4):
                    norm += abs(P2[i]-P[i])
                # this is slower: norm = sum(abs(x-y) for (x,y) in zip(P2,P))
                if norm < 0.001:
                    steady = True
                for i in xrange(4):
                    P[i] = P2[i]
            else:
                v = self.steady_update(y,a,K)
                
            t1 += v**2/F
            t2 += lF

        if t1 == 0.: return -t2
        return -len(data)*log(t1) - t2


    def llh_old(self,zeta,datarange=100):
        """ The concentrated diffuse loglikelihood function. """
        data = self.data[self.first_forecast_index():datarange]
        a = [2.*self.data[1]-self.data[0],self.data[1]-self.data[0]]
        P = [5.+2.*zeta,3.+zeta, 3.+zeta,2.+zeta]
        P2 = [None]*4
        F = P[0]+1.0
        lF = log(F)
        K = [(P[0]+P[2])/F, P[2]/F]
        t1, t2 = 0., 0.
        for [a,v,F,lF,P] in self.next_state(data,a,P,P2,K,lF,zeta):
            t1 += v**2/F
            t2 += lF

        if t1 == 0.: return -t2
        return -len(data)*log(t1) - t2



    def update(self, k):
        Z = [1., 0.]
        Q = 0.0
        
        psi = vec([1.0])
        dfpmin(lambda x: -self.llh(exp(x),k), psi)
        Q = zeta = exp(psi[0]) #exp(psi[0]/10.)
        
        a = [2.*self.data[1]-self.data[0],self.data[1]-self.data[0]]
        P = [5.+2.*zeta,3.+zeta, 3.+zeta,2.+zeta]
        P2 = [None]*4
        F = P[0]+1.0
        lF = log(F)
        K = [(P[0]+P[2])/F, P[2]/F]
        
        epsilon = 0.
        data = self.data[self.first_forecast_index():k]

        steady = False
        for y in data:
            if not steady:
                [v,F,lF] = self.update_kalman(y,a,P,P2,K,zeta)
                norm = 0
                for i in xrange(4):
                    norm += abs(P2[i]-P[i])
                if norm < 0.001:
                    steady = True
                for i in xrange(4):
                    P[i] = P2[i]
            else:
                v = self.steady_update(y,a,K)
                
            epsilon += v*v/F

        self.epsilon = epsilon/len(data)
        self.zeta = zeta*self.epsilon
        self.trend = a[1]
        self.fc[k] = a[0]
        self.var = self.p[k] = (P[0] + 1)*self.epsilon


    def variance(self,i):
        n = len(self.data)
        if i < n-2:
            return self.p[i]
        else:
            return self.var + (i-n+3)*self.zeta #+ self.epsilon

    def predict(self, length):
        if length <= self.forecast_len: return 0.0
        nn = len(self.fc)
        ext = length-self.forecast_len
        self.fc.extend([None]*ext)
        self.p.extend([None]*ext)
        for i in range(ext):
            self.fc[nn+i] = self.fc[nn-1] + self.trend
            self.p[nn+i] = self.p[nn+i-1] + self.zeta #+ self.epsilon


    def datalen(self):
        return len(self.data)


class LLB:
    """ Multivariate Local Level """
        
    eps = 1e-12

    def __init__(self, data, forecast_len=FORECAST):
        if len(data) == 0: raise ValueError
        self.data = data
        self.forecast_len = forecast_len
        self.Q = [None]*3
        self.P = [None]*(len(data)+self.forecast_len) # variances of predictions (not filtered states)
        self.a = [None]*len(self.P) # filter states
        self.a[0] = [data[0][0],data[0][1]]
        self.scale = .1

        for i in xrange(1,len(data)):
            self.update(i)


    @classmethod
    def load(cls,file): # each line consists of a pair of numbers separated by spaces
        f = open(file,'r')
        data = [map(float,line.strip().split()) for line in f]
        f.close()
        cls = LLB(data)
        return cls


    @classmethod
    def loadlog(cls,file):
        f = open(file,'r')
        data = [map(lambda x: log(float(x)),line.strip().split()) for line in f]
        f.close()
        cls = LLB(data)
        return cls


    @classmethod
    def instance(cls, var1, var2, forecast_len=FORECAST):
        cls = LLB(zip(var1,var2),forecast_len)
        return cls

    @classmethod
    def least_num_data(cls):
        return 2

    @classmethod
    def first_forecast_index(cls):
        return 1 
    

    def update_Kalman(self,y,a,v,P,K,Fi):
        detP = P[0]*P[2] - P[1]*P[1]
        trP = P[0] + P[2]
        detF = detP + trP + 1.
        
        Fi[0] = (P[2]+1.)/detF
        Fi[1] = -P[1]/detF
        Fi[2] = (P[0]+1.)/detF

        K[0] = (P[0]+detP)/detF
        K[1] = -Fi[1] # = P[1]/detF
        K[2] = (P[2]+detP)/detF

        v[0] = y[0] - a[0]
        v[1] = y[1] - a[1]

        a[0] += K[0]*v[0] + K[1]*v[1]
        a[1] += K[1]*v[0] + K[2]*v[1]

        PP1 = K[0] + self.Q[0]
        PP2 = K[1] + self.Q[1]
        PP3 = K[2] + self.Q[2]
        PP = abs(PP1-P[0]) + abs(PP2-P[1]) + abs(PP3-P[2])
        if PP < 1.0e-5: steady = True
        else: steady = False
        P[0],P[1],P[2] = PP1,PP2,PP3

        return detF, steady


    def update_steady(self,y,a,v,K):
        v[0] = y[0] - a[0]
        v[1] = y[1] - a[1]
        a[0] += K[0]*v[0] + K[1]*v[1]
        a[1] += K[1]*v[0] + K[2]*v[1]
        
        
    # start = where to begin in data
    def next_state(self,data,start,a,v,P,K,Fi):
        steady = False
        for i in xrange(start,len(data)):
            if not steady:
                detF,steady = self.update_Kalman(data[i],a,v,P,K,Fi)
            else: self.update_steady(data[i],a,v,K)
            yield detF


    def llh(self, t1,t2,t3, datarange=200):
        data = self.data[:datarange]

        # self.Q[0] = exp(self.scale*t1)
        # self.Q[1] = exp(self.scale*t1/2.)*t2
        # self.Q[2] = exp(self.scale*t3) + t2**2
        eps = LLB.eps
        self.Q[0] = t1**2+eps 
        self.Q[1] = (abs(t1)+eps)*t2
        self.Q[2] = t3**2+eps+t2**2 

        a = [self.data[0][0],self.data[0][1]]
        P = [self.Q[0]+1., self.Q[1], self.Q[2]+1.]
        K = [0.]*3
        Fi = [1.,0.,1.]
        v = [0.]*2
        t1, t2 = 0., 0.
        
        steady = False
        for detF in self.next_state(data,1,a,v,P,K,Fi):
            t1 += v[0]*Fi[0]*v[0] + 2*v[0]*Fi[1]*v[1] + v[1]*Fi[2]*v[1]
            t2 += log(detF)

        if t1 == 0.: return t2/2.
        return (len(data)-1)*log(t1) + t2/2.


    def update(self, k):
        psi = vec([1./self.scale, .5/self.scale, 1./self.scale])
        dfpmin(lambda x,y,z: self.llh(x,y,z,k), psi)

        eps = LLB.eps
        [t1,t2,t3] = psi
        self.Q[0] = t1**2+eps 
        self.Q[1] = (abs(t1)+eps)*t2
        self.Q[2] = t3**2+eps+t2**2 
        
        # self.Q[0] =  exp(self.scale*psi[0])
        # self.Q[1] = exp(self.scale*psi[0]/2.)*psi[1]
        # self.Q[2] = exp(self.scale*psi[2]) + psi[1]**2

        data = self.data[:k]

        a = [self.data[0][0],self.data[0][1]]
        P = [self.Q[0]+1., self.Q[1], self.Q[2]+1.]
        K = [0.]*3
        Fi = [1.,0.,1.]
        v = [0.]*2

        epsilon = 0.
        steady = False
        for i,detF in enumerate(self.next_state(data,1,a,v,P,K,Fi)):
            epsilon += v[0]*Fi[0]*v[0] + 2*v[0]*Fi[1]*v[1] +  v[1]*Fi[2]*v[1]
        epsilon /= 2.*k
        
        self.epsilon = epsilon
        self.Q = [epsilon*t for t in self.Q]
        self.P[k] = [(P[0]+1)*epsilon,P[1]*epsilon,(P[2]+1)*epsilon]
        self.a[k] = [a[0],a[1]]


    def predict(self, var, start=30):
        if var != 0 and var != 1: raise ValueError

        data = self.data
        n = len(data)

        corvar = 1-var

        self.fc = [None]*n
        self.VAR = [None]*n
        for i in xrange(start,n):
            j = i-start
            COV = self.P[i] 
            if COV[2*corvar] != 0:
                SIGMA = COV[1]/COV[2*corvar]
                self.VAR[i] = COV[2*var] - COV[1]*COV[1]/COV[2*corvar]                
            else:
                SIGMA = 0
                self.VAR[i] = COV[2*var]

            self.fc[i] = self.a[i-1][var] + SIGMA*(data[i][corvar] - self.a[i-1][corvar])



    def variance(self,i):
        return self.VAR[i]


    def datalen(self):
        return len(self.data)


# def computeStats(model):
#     n = len(model.data)

#     model.r = [None]*n # autocorrelation (Commandeur-Koopman, p.90)
#     model.Q = [None]*n # Box-Ljung statistic (Commandeur-Koopman, p.90)
#     model.H = [None]*n # Homoscedasticity (Commandeur-Koopman, p.92)

#     nf = n - 1.
#     e_mean = sum(model.e)/nf
#     model.var = reduce(lambda x,y: x + (y-e_mean)**2,model.e[1:],0.0) 
    
#     for k in range(1,len(model.r)):
#         model.r[k] = reduce(lambda x,y: x + (y[0]-e_mean)*(y[1]-e_mean), izip(model.e,model.e[k:]), 0.0)/model.var
        
#     for k in range(1,len(model.Q)):
#         model.Q[k] = n*(n+2)*reduce(lambda x,y: x + y[1]**2/(n-y[0]-1.), enumerate(model.r[1:k+1]), 0.0)
#             # explain: n-y[0]-1. we subtract 1 because we start from the index 1 term of model.r while enumerate starts from 0.
            
#     esq = [e**2 for e in model.e]
#     d = 1
#     for h in range(1,len(model.H)):
#         denom = sum(esq[d:d+h])
#         if denom == 0: model.H[h] = 100000.
#         else: model.H[h] = sum(esq[n-h:])/denom
                
#     m2 = model.var/nf
#     m3 = reduce(lambda x,y: x + (y-e_mean)**3, model.e[1:], 0.0)/nf
#     m4 = reduce(lambda x,y: x + (y-e_mean)**4, model.e[1:], 0.0)/nf
#     model.S = m3/m2**(3.0/2)
#     model.K = m4/(m2**2)
#     model.N = nf*(model.S**2/6. + (model.K-3)**2/24.)
                
 
# def independence(model, k):
#     critical_val = Chisqdist(k-model.w+1).invcdf(.95)
#     if model.Q[k] < critical_val: 
#         print "Q = %f, critical = %f" %(model.Q[k],critical_val)
#         return True
#     else:
#         print "independence fails: Q[%d] = %f >= critical_val = %f" %(k,model.Q[k],critical_val)
#     return False

# def homoscedasticity(model):
#     k = int(round((len(model.data) - 1)/3.,0))
#     critical_val = Fdist(k,k).invcdf(.975)
#     if model.H[k] < critical_val: 
#         print "H = %f, critical_val = %f" %(model.H[k],critical_val)
#         return True
#     else:
#         print "homoscedasticity fails: H[%d] = %f >= critical_val = %f" %(k,model.H[k],critical_val)
#     return False
        
# def normality(model):
#     if model.N < normality_critical_val: 
#         print "N = %f, critical_val = %f" %(model.N,normality_critical_val)
#         return True
#     else:
#         print "normality fails: N = %f >= critical_val = %f" %(model.N,normality_critical_val)
#     return False

# def box_ljung (model,k):
#     if k >= len(model.Q):
#         print "Box-Ljung statistic only computed for 1 <= k <= %d" %len(model.Q)
#         raise ValueError
#     return model.Q[k]
