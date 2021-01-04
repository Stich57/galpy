###############################################################################
#   DoubleExponentialDiskPotential.py: class that implements the double
#                                      exponential disk potential
#
#                                      rho(R,z) = rho_0 e^-R/h_R e^-|z|/h_z
###############################################################################
import numpy
from scipy import special
from ..util import conversion
from .PowerSphericalPotential import KeplerPotential
from .Potential import Potential
_TOL= 1.4899999999999999e-15
_MAXITER= 20

def _de_psi(t):
    return t*numpy.tanh(numpy.pi/2.*numpy.sinh(t))
def _de_psiprime(t):
    return (numpy.sinh(numpy.pi*numpy.sinh(t))
            +numpy.pi*t*numpy.cosh(t))/(numpy.cosh(numpy.pi*numpy.sinh(t))+1)

class DoubleExponentialDiskPotential(Potential):
    """Class that implements the double exponential disk potential

    .. math::

        \\rho(R,z) = \\mathrm{amp}\\,\\exp\\left(-R/h_R-|z|/h_z\\right)

    """
    def __init__(self,amp=1.,hr=1./3.,hz=1./16.,
                 maxiter=_MAXITER,tol=0.001,normalize=False,
                 ro=None,vo=None,
                 new=True,kmaxFac=2.,glorder=10,
                 de=True,de_h=1e-3,de_n=10000):
        """
        NAME:

           __init__

        PURPOSE:

           initialize a double-exponential disk potential

        INPUT:

           amp - amplitude to be applied to the potential (default: 1); can be a Quantity with units of mass density or Gxmass density

           hr - disk scale-length (can be Quantity)

           hz - scale-height (can be Quantity)

           tol - relative accuracy of potential-evaluations

           maxiter - scipy.integrate keyword

           normalize - if True, normalize such that vc(1.,0.)=1., or, if given as a number, such that the force is this fraction of the force necessary to make vc(1.,0.)=1.

           ro=, vo= distance and velocity scales for translation into internal units (default from configuration file)

        OUTPUT:

           DoubleExponentialDiskPotential object

        HISTORY:

           2010-04-16 - Written - Bovy (NYU)

           2013-01-01 - Re-implemented using faster integration techniques - Bovy (IAS)

           2020-12-24 - Re-implemented again using more accurate integration techniques for Bessel integrals - Bovy (UofT)

        """
        Potential.__init__(self,amp=amp,ro=ro,vo=vo,amp_units='density')
        hr= conversion.parse_length(hr,ro=self._ro)
        hz= conversion.parse_length(hz,ro=self._ro)
        self.hasC= True
        self.hasC_dens= True
        self._kmaxFac= kmaxFac
        self._glorder= glorder
        self._hr= hr
        self._scale= self._hr
        self._hz= hz
        self._alpha= 1./self._hr
        self._beta= 1./self._hz
        self._gamma= self._alpha/self._beta
        self._maxiter= maxiter
        self._tol= tol
        self._zforceNotSetUp= True #We have not calculated a typical Kz yet
        #Setup j0 zeros etc.
        self._glx, self._glw= numpy.polynomial.legendre.leggauss(self._glorder)
        self._nzeros=100
        #j0 for potential and z
        self._j0zeros= numpy.zeros(self._nzeros+1)
        self._j0zeros[1:self._nzeros+1]= special.jn_zeros(0,self._nzeros)
        self._dj0zeros= self._j0zeros-numpy.roll(self._j0zeros,1)
        self._dj0zeros[0]= self._j0zeros[0]
        #j1 for R
        self._j1zeros= numpy.zeros(self._nzeros+1)
        self._j1zeros[1:self._nzeros+1]= special.jn_zeros(1,self._nzeros)
        self._dj1zeros= self._j1zeros-numpy.roll(self._j1zeros,1)
        self._dj1zeros[0]= self._j1zeros[0]
        #j2 for R2deriv
        self._j2zeros= numpy.zeros(self._nzeros+1)
        self._j2zeros[1:self._nzeros+1]= special.jn_zeros(2,self._nzeros)
        self._dj2zeros= self._j2zeros-numpy.roll(self._j2zeros,1)
        self._dj2zeros[0]= self._j2zeros[0]
        # For double-exponential formula
        self._de= de
        self._de_h= de_h
        self._de_n= de_n
        self._de_j0zeros= special.jn_zeros(0,self._de_n)/numpy.pi
        self._de_j1zeros= special.jn_zeros(1,self._de_n)/numpy.pi
        self._de_j0_xs= numpy.pi/self._de_h\
            *_de_psi(self._de_h*self._de_j0zeros)
        self._de_j0_weights= 2./(numpy.pi*self._de_j0zeros\
                               *special.j1(numpy.pi*self._de_j0zeros)**2.)\
                               *special.j0(self._de_j0_xs)\
                               *_de_psiprime(self._de_h*self._de_j0zeros)
        self._de_j1_xs= numpy.pi/self._de_h\
            *_de_psi(self._de_h*self._de_j1zeros)
        self._de_j1_weights= 2./(numpy.pi*self._de_j1zeros\
                               *special.jv(2,numpy.pi*self._de_j1zeros)**2.)\
                               *special.j1(self._de_j1_xs)\
                               *_de_psiprime(self._de_h*self._de_j1zeros)
        # Normalize?
        if normalize or \
                (isinstance(normalize,(int,float)) \
                     and not isinstance(normalize,bool)): #pragma: no cover
            self.normalize(normalize)
        #Load Kepler potential for large R
        self._kp= KeplerPotential(normalize=4.*numpy.pi/self._alpha**2./self._beta)

    def _evaluate(self,R,z,phi=0.,t=0.,dR=0,dphi=0):
        """
        NAME:
           _evaluate
        PURPOSE:
           evaluate the potential at (R,z)
        INPUT:
           R - Cylindrical Galactocentric radius
           z - vertical height
           phi - azimuth
           t - time
        OUTPUT:
           potential at (R,z)
        HISTORY:
           2010-04-16 - Written - Bovy (NYU)
           2012-12-26 - New method using Gaussian quadrature between zeros - Bovy (IAS)
           2020-12-24 - New method using Ogata's Bessel integral formula - Bovy (UofT)
        """
        if isinstance(R,(float,int)):
            floatIn= True
            R= numpy.array([R])
            z= numpy.array([z])
        else:
            if isinstance(z,float):
                z= z*numpy.ones_like(R)
            floatIn= False
            outShape= R.shape # this code can't do arbitrary shapes
            R= R.flatten()
            z= z.flatten()
        if self._de:
            fun= lambda x: (self._alpha**2.+(x/R[:,numpy.newaxis])**2.)**-1.5\
                *(self._beta*numpy.exp(-x/R[:,numpy.newaxis]*numpy.fabs(z[:,numpy.newaxis]))
                  -x/R[:,numpy.newaxis]*numpy.exp(-self._beta*numpy.fabs(z[:,numpy.newaxis])))\
                  /(self._beta**2.-(x/R[:,numpy.newaxis])**2.)
            out= -4.*numpy.pi*self._alpha/R*\
                numpy.nansum(fun(self._de_j0_xs)*self._de_j0_weights,
                             axis=1)
            if floatIn: return out[0]
            else: return numpy.reshape(out,outShape)
        if True:
            out= numpy.empty(len(R))
            indx= (R <= 6.)
            if numpy.sum(True^indx) > 0:
                out[True^indx]= self._kp(R[True^indx],z[True^indx])
            R4max= numpy.copy(R)
            R4max[(R < 1.)]= 1.
            kmax= self._kmaxFac*self._beta
            for jj in range(len(R)):
                if not indx[jj]: continue
                maxj0zeroIndx= numpy.argmin((self._j0zeros-kmax*R4max[jj])**2.) #close enough
                ks= numpy.array([0.5*(self._glx+1.)*self._dj0zeros[ii+1] + self._j0zeros[ii] for ii in range(maxj0zeroIndx)]).flatten()
                weights= numpy.array([self._glw*self._dj0zeros[ii+1] for ii in range(maxj0zeroIndx)]).flatten()
                evalInt= special.jn(0,ks*R[jj])*(self._alpha**2.+ks**2.)**-1.5*(self._beta*numpy.exp(-ks*numpy.fabs(z[jj]))-ks*numpy.exp(-self._beta*numpy.fabs(z[jj])))/(self._beta**2.-ks**2.)
                out[jj]= -2.*numpy.pi*self._alpha*numpy.sum(weights*evalInt)
            if floatIn: return out[0]
            else: return numpy.reshape(out,outShape)
    
    def _Rforce(self,R,z,phi=0.,t=0.):
        """
        NAME:
           Rforce
        PURPOSE:
           evaluate radial force K_R  (R,z)
        INPUT:
           R - Cylindrical Galactocentric radius
           z - vertical height
           phi - azimuth
           t - time
        OUTPUT:
           K_R (R,z)
        HISTORY:
           2010-04-16 - Written - Bovy (NYU)
           2012-12-26 - New method using Gaussian quadrature between zeros - Bovy (IAS)
           2020-12-24 - New method using Ogata's Bessel integral formula - Bovy (UofT)
        """
        if self._de:
            fun=  lambda x: x*(self._alpha**2.+(x/R)**2.)**-1.5\
                *(self._beta*numpy.exp(-x/R*numpy.fabs(z))
                  -x/R*numpy.exp(-self._beta*numpy.fabs(z)))\
                  /(self._beta**2.-(x/R)**2.)
            return -4.*numpy.pi*self._alpha/R**2.\
                *numpy.nansum(fun(self._de_j1_xs)*self._de_j1_weights)
        if True:
            if isinstance(R,numpy.ndarray):
                if not isinstance(z,numpy.ndarray): z= numpy.ones_like(R)*z
                out= numpy.array([self._Rforce(rr,zz) for rr,zz in zip(R,z)])
                return out
            if (R > 16.*self._hr or R > 6.) and hasattr(self,'_kp'): return self._kp.Rforce(R,z)
            if R < 1.: R4max= 1.
            else: R4max= R
            kmax= self._kmaxFac*self._beta
            kmax= 2.*self._kmaxFac*self._beta
            maxj1zeroIndx= numpy.argmin((self._j1zeros-kmax*R4max)**2.) #close enough
            ks= numpy.array([0.5*(self._glx+1.)*self._dj1zeros[ii+1] + self._j1zeros[ii] for ii in range(maxj1zeroIndx)]).flatten()
            weights= numpy.array([self._glw*self._dj1zeros[ii+1] for ii in range(maxj1zeroIndx)]).flatten()
            evalInt= ks*special.jn(1,ks*R)*(self._alpha**2.+ks**2.)**-1.5*(self._beta*numpy.exp(-ks*numpy.fabs(z))-ks*numpy.exp(-self._beta*numpy.fabs(z)))/(self._beta**2.-ks**2.)
            return -2.*numpy.pi*self._alpha*numpy.sum(weights*evalInt)
    
    def _zforce(self,R,z,phi=0.,t=0.):
        """
        NAME:
           zforce
        PURPOSE:
           evaluate vertical force K_z  (R,z)
        INPUT:
           R - Cylindrical Galactocentric radius
           z - vertical height
           phi - azimuth
           t - time
        OUTPUT:
           K_z (R,z)
        HISTORY:
           2010-04-16 - Written - Bovy (NYU)
           2012-12-26 - New method using Gaussian quadrature between zeros - Bovy (IAS)
           2020-12-24 - New method using Ogata's Bessel integral formula - Bovy (UofT)
        """
        if self._de:
            fun= lambda x: (self._alpha**2.+(x/R)**2.)**-1.5*x/R\
                *(numpy.exp(-x/R*numpy.fabs(z))
                  -numpy.exp(-self._beta*numpy.fabs(z)))\
                  /(self._beta**2.-(x/R)**2.)
            out= -4.*numpy.pi*self._alpha*self._beta/R*\
                numpy.nansum(fun(self._de_j0_xs)*self._de_j0_weights)
            if z > 0.:
                return out
            else:
                return -out
        if True:
            if isinstance(R,numpy.ndarray):
                if not isinstance(z,numpy.ndarray): z= numpy.ones_like(R)*z
                out= numpy.array([self._zforce(rr,zz) for rr,zz in zip(R,z)])
                return out
            if R > 16.*self._hr or R > 6.: return self._kp.zforce(R,z)
            if R < 1.: R4max= 1.
            else: R4max= R
            kmax= self._kmaxFac*self._beta
            maxj0zeroIndx= numpy.argmin((self._j0zeros-kmax*R4max)**2.) #close enough
            ks= numpy.array([0.5*(self._glx+1.)*self._dj0zeros[ii+1] + self._j0zeros[ii] for ii in range(maxj0zeroIndx)]).flatten()
            weights= numpy.array([self._glw*self._dj0zeros[ii+1] for ii in range(maxj0zeroIndx)]).flatten()
            evalInt= ks*special.jn(0,ks*R)*(self._alpha**2.+ks**2.)**-1.5*(numpy.exp(-ks*numpy.fabs(z))-numpy.exp(-self._beta*numpy.fabs(z)))/(self._beta**2.-ks**2.)
            if z > 0.:
                return -2.*numpy.pi*self._alpha*self._beta*numpy.sum(weights*evalInt)
            else:
                return 2.*numpy.pi*self._alpha*self._beta*numpy.sum(weights*evalInt)

    def _R2deriv(self,R,z,phi=0.,t=0.):
        """
        NAME:
           R2deriv
        PURPOSE:
           evaluate R2 derivative
        INPUT:
           R - Cylindrical Galactocentric radius
           z - vertical height
           phi - azimuth
           t - time
        OUTPUT:
           -d K_R (R,z) d R
        HISTORY:
           2012-12-27 - Written - Bovy (IAS)
           2020-12-24 - New method using Ogata's Bessel integral formula - Bovy (UofT)
        """
        if self._de:
            fun=  lambda x: x**2*(self._alpha**2.+(x/R)**2.)**-1.5\
                *(self._beta*numpy.exp(-x/R*numpy.fabs(z))
                  -x/R*numpy.exp(-self._beta*numpy.fabs(z)))\
                  /(self._beta**2.-(x/R)**2.)
            return 4.*numpy.pi*self._alpha/R**3.\
                *numpy.nansum(fun(self._de_j0_xs)*self._de_j0_weights
                              -fun(self._de_j1_xs)/self._de_j1_xs\
                                  *self._de_j1_weights)
        if True:
            if isinstance(R,numpy.ndarray):
                if not isinstance(z,numpy.ndarray): z= numpy.ones_like(R)*z
                out= numpy.array([self._R2deriv(rr,zz) for rr,zz in zip(R,z)])
                return out
            if R > 16.*self._hr or R > 6.: return self._kp.R2deriv(R,z)
            if R < 1.: R4max= 1.
            else: R4max= R
            kmax= 2.*self._kmaxFac*self._beta
            maxj0zeroIndx= numpy.argmin((self._j0zeros-kmax*R4max)**2.) #close enough
            maxj2zeroIndx= numpy.argmin((self._j2zeros-kmax*R4max)**2.) #close enough
            ks0= numpy.array([0.5*(self._glx+1.)*self._dj0zeros[ii+1] + self._j0zeros[ii] for ii in range(maxj0zeroIndx)]).flatten()
            weights0= numpy.array([self._glw*self._dj0zeros[ii+1] for ii in range(maxj0zeroIndx)]).flatten()
            ks2= numpy.array([0.5*(self._glx+1.)*self._dj2zeros[ii+1] + self._j2zeros[ii] for ii in range(maxj2zeroIndx)]).flatten()
            weights2= numpy.array([self._glw*self._dj2zeros[ii+1] for ii in range(maxj2zeroIndx)]).flatten()
            evalInt0= ks0**2.*special.jn(0,ks0*R)*(self._alpha**2.+ks0**2.)**-1.5*(self._beta*numpy.exp(-ks0*numpy.fabs(z))-ks0*numpy.exp(-self._beta*numpy.fabs(z)))/(self._beta**2.-ks0**2.)
            evalInt2= ks2**2.*special.jn(2,ks2*R)*(self._alpha**2.+ks2**2.)**-1.5*(self._beta*numpy.exp(-ks2*numpy.fabs(z))-ks2*numpy.exp(-self._beta*numpy.fabs(z)))/(self._beta**2.-ks2**2.)
            return numpy.pi*self._alpha*(numpy.sum(weights0*evalInt0)
                                      -numpy.sum(weights2*evalInt2))
    
    def _z2deriv(self,R,z,phi=0.,t=0.):
        """
        NAME:
           z2deriv
        PURPOSE:
           evaluate z2 derivative
        INPUT:
           R - Cylindrical Galactocentric radius
           z - vertical height
           phi - azimuth
           t - time
        OUTPUT:
           -d K_Z (R,z) d Z
        HISTORY:
           2012-12-26 - Written - Bovy (IAS)
           2020-12-24 - New method using Ogata's Bessel integral formula - Bovy (UofT)
        """
        if self._de:
            fun= lambda x: (self._alpha**2.+(x/R)**2.)**-1.5*x/R\
                *(x/R*numpy.exp(-x/R*numpy.fabs(z))
                  -self._beta*numpy.exp(-self._beta*numpy.fabs(z)))\
                  /(self._beta**2.-(x/R)**2.)
            return -4.*numpy.pi*self._alpha*self._beta/R*\
                numpy.nansum(fun(self._de_j0_xs)*self._de_j0_weights)
        if True:
            if isinstance(R,numpy.ndarray):
                if not isinstance(z,numpy.ndarray): z= numpy.ones_like(R)*z
                out= numpy.array([self._z2deriv(rr,zz) for rr,zz in zip(R,z)])
                return out
            if R > 16.*self._hr or R > 6.: return self._kp.z2deriv(R,z)
            if R < 1.: R4max= 1.
            else: R4max= R
            kmax= self._kmaxFac*self._beta
            maxj0zeroIndx= numpy.argmin((self._j0zeros-kmax*R4max)**2.) #close enough
            ks= numpy.array([0.5*(self._glx+1.)*self._dj0zeros[ii+1] + self._j0zeros[ii] for ii in range(maxj0zeroIndx)]).flatten()
            weights= numpy.array([self._glw*self._dj0zeros[ii+1] for ii in range(maxj0zeroIndx)]).flatten()
            evalInt= ks*special.jn(0,ks*R)*(self._alpha**2.+ks**2.)**-1.5*(ks*numpy.exp(-ks*numpy.fabs(z))-self._beta*numpy.exp(-self._beta*numpy.fabs(z)))/(self._beta**2.-ks**2.)
            return -2.*numpy.pi*self._alpha*self._beta*numpy.sum(weights*evalInt)

    def _Rzderiv(self,R,z,phi=0.,t=0.):
        """
        NAME:
           Rzderiv
        PURPOSE:
           evaluate the mixed R,z derivative
        INPUT:
           R - Cylindrical Galactocentric radius
           z - vertical height
           phi - azimuth
           t - time
        OUTPUT:
           d2phi/dR/dz
        HISTORY:
           2013-08-28 - Written - Bovy (IAS)
           2020-12-24 - New method using Ogata's Bessel integral formula - Bovy (UofT)
        """
        if self._de:
            fun= lambda x: (self._alpha**2.+(x/R)**2.)**-1.5*(x/R)**2.\
                *(numpy.exp(-x/R*numpy.fabs(z))
                  -numpy.exp(-self._beta*numpy.fabs(z)))\
                  /(self._beta**2.-(x/R)**2.)
            out= -4.*numpy.pi*self._alpha*self._beta/R*\
                numpy.nansum(fun(self._de_j1_xs)*self._de_j1_weights)
            if z > 0.:
                return out
            else:
                return -out
        if True:
            if isinstance(R,numpy.ndarray):
                if not isinstance(z,numpy.ndarray): z= numpy.ones_like(R)*z
                out= numpy.array([self._Rzderiv(rr,zz) for rr,zz in zip(R,z)])
                return out
            if R > 6.: return self._kp.Rzderiv(R,z)
            if R < 1.: R4max= 1.
            else: R4max= R
            kmax= 2.*self._kmaxFac*self._beta
            maxj1zeroIndx= numpy.argmin((self._j1zeros-kmax*R4max)**2.) #close enough
            ks= numpy.array([0.5*(self._glx+1.)*self._dj1zeros[ii+1] + self._j1zeros[ii] for ii in range(maxj1zeroIndx)]).flatten()
            weights= numpy.array([self._glw*self._dj1zeros[ii+1] for ii in range(maxj1zeroIndx)]).flatten()
            evalInt= ks**2.*special.jn(1,ks*R)*(self._alpha**2.+ks**2.)**-1.5*(numpy.exp(-ks*numpy.fabs(z))-numpy.exp(-self._beta*numpy.fabs(z)))/(self._beta**2.-ks**2.)
            if z >= 0.:
                return -2.*numpy.pi*self._alpha*self._beta*numpy.sum(weights*evalInt)
            else:
                return 2.*numpy.pi*self._alpha*self._beta*numpy.sum(weights*evalInt)

    def _dens(self,R,z,phi=0.,t=0.):
        """
        NAME:
           _dens
        PURPOSE:
           evaluate the density
        INPUT:
           R - Cylindrical Galactocentric radius
           z - vertical height
           phi - azimuth
           t - time
        OUTPUT:
           rho (R,z)
        HISTORY:
           2010-08-08 - Written - Bovy (NYU)
        """
        return numpy.exp(-self._alpha*R-self._beta*numpy.fabs(z))

    def _surfdens(self,R,z,phi=0.,t=0.):
        """
        NAME:
           _surfdens
        PURPOSE:
           evaluate the surface density
        INPUT:
           R - Cylindrical Galactocentric radius
           z - vertical height
           phi - azimuth
           t - time
        OUTPUT:
           Sigma (R,z)
        HISTORY:
           2018-08-19 - Written - Bovy (UofT)
        """
        return 2.*numpy.exp(-self._alpha*R)/self._beta\
            *(1.-numpy.exp(-self._beta*numpy.fabs(z)))
