"""
Copyright (C) 2009-2013 Jussi Leinonen

Permission is hereby granted, free of charge, to any person obtaining a copy of
this software and associated documentation files (the "Software"), to deal in
the Software without restriction, including without limitation the rights to
use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
the Software, and to permit persons to whom the Software is furnished to do so,
subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
"""

from datetime import datetime
try:
    import cPickle as pickle
except ImportError:
    import pickle
import warnings
import numpy as np
from scipy.integrate import trapz
from scipy.special import gamma
import tmatrix_aux


class GammaPSD(object):
    """Normalized gamma particle size distribution (PSD).
    
    Callable class to provide a normalized gamma PSD with the given 
    parameters. The attributes can also be given as arguments to the 
    constructor.

    Attributes:
        D0: the median volume diameter.
        Nw: the intercept parameter.
        mu: the shape parameter.
        D_max: the maximum diameter to consider (defaults to 3*D0 when
            the class is initialized but must be manually changed afterwards)

    Args (call):
        D: the particle diameter.

    Returns (call):
        The PSD value for the given diameter.    
        Returns 0 for all diameters larger than D_max.
    """

    def __init__(self, D0=1.0, Nw=1.0, mu=0.0):
        self.D0 = float(D0)
        self.mu = float(mu)
        self.D_max = 3.0 * D0
        self.Nw = float(Nw)
        self.nf = Nw * 6.0/3.67**4 * (3.67+mu)**(mu+4)/gamma(mu+4)

    def __call__(self, D):
        d = (D/self.D0)
        psd = self.nf * d**self.mu * np.exp(-(3.67+self.mu)*d)
        if np.shape(D) == ():
            if D > self.D_max:
                return 0.0
        else:
            psd[D > self.D_max] = 0.0
        return psd

    def __eq__(self, other):
        try:
            return isinstance(other, GammaPSD) and (self.D0 == other.D0) and \
                (self.Nw == other.Nw) and (self.mu == other.mu) and \
                (self.D_max == other.D_max)
        except AttributeError:
            return False


class BinnedPSD(object):
    """Binned gamma particle size distribution (PSD).
    
    Callable class to provide a binned PSD with the given bin edges and PSD
    values.

    Args (constructor):
        The first argument to the constructor should specify n+1 bin edges, 
        and the second should specify n bin_psd values.        
        
    Args (call):
        D: the particle diameter.

    Returns (call):
        The PSD value for the given diameter.    
        Returns 0 for all diameters outside the bins.
    """
    
    def __init__(self, bin_edges, bin_psd):
        if len(bin_edges) != len(bin_psd)+1:
            raise ValueError("There must be n+1 bin edges for n bins.")
        
        self.bin_edges = bin_edges
        self.bin_psd = bin_psd
        
    def psd_for_D(self, D):       
        if not (self.bin_edges[0] < D <= self.bin_edges[-1]):
            return 0.0
        
        # binary search for the right bin
        start = 0
        end = len(self.bin_edges)
        while end-start > 1:
            half = (start+end)//2
            if self.bin_edges[start] < D <= self.bin_edges[half]:
                end = half
            else:
                start = half
                                
        return bin_psd[start]                    
        
    def __call__(self, D):
        if np.shape(D) == (): # D is a scalar
            return self.psd_for_D(D)
        else:
            return np.array([self.psd_for_D(d) for d in D])
    
    def __eq__(self, other):
        return len(self.bin_edges) == len(other.bin_edges) and \
            (self.bin_edges == other.bin_edges).all() and \
            (self.bin_psd == other.bin_psd).all()


class PSDIntegrator(object):

    def __init__(self, **kwargs):      
        self.num_points = 500
        self.m_func = None
        self.eps_func = None
        self.D_max = None
        self.geometries = (tmatrix_aux.geom_horiz_back,)

        attrs = ("num_points", "m_func", "eps_func", "D_max", "geometries")
        for k in kwargs:
            if k in attrs:
                self.__dict__[k] = kwargs[k]

        self._S_table = None
        self._Z_table = None
        self._previous_psd = None


    def __call__(self, psd, geometry):
        return self.get_SZ(psd, geometry)


    def get_SZ(self, psd, geometry):
        """
        Compute the scattering matrices for the given PSD and geometries.

        Returns:
            The new amplitude (S) and phase (Z) matrices.
        """
        if (self._S_table is None) or (self._Z_table is None):
            raise AttributeError(
                "Initialize or load the scattering table first.")

        if self._previous_psd != psd:
            self._S_dict = {}
            self._Z_dict = {}
            psd_w = psd(self._psd_D)

            for geom in self.geometries:
                self._S_dict[geom] = \
                    trapz(self._S_table[geom] * psd_w, self._psd_D)
                self._Z_dict[geom] = \
                    trapz(self._Z_table[geom] * psd_w, self._psd_D)

            self._previous_psd = psd

        return (self._S_dict[geometry], self._Z_dict[geometry])


    def init_scatter_table(self, tm):
        """Initialize the scattering lookup tables.
        
        Initialize the scattering lookup tables for the different geometries.
        Before calling this, the following attributes must be set:
           num_points, m_func, eps_func, D_max, geometries
        and additionally, all the desired attributes of the TMatrix class
        (e.g. wavelength, aspect ratio).
        """
        self._psd_D = \
            np.linspace(self.D_max/self.num_points, self.D_max, self.num_points)

        self._S_table = {}
        self._Z_table = {}
        self._previous_psd = None
        self._m_table = np.ndarray(self.num_points, dtype=complex)
        
        (old_m, old_eps, old_axi, old_geom) = \
            (tm.m, tm.eps, tm.axi, tm.get_geometry())

        for geom in self.geometries:
            self._S_table[geom] = \
                np.ndarray((2,2,self.num_points), dtype=complex)
            self._Z_table[geom] = np.ndarray((4,4,self.num_points))

        for (i,D) in enumerate(self._psd_D):
            if self.m_func != None:
                tm.m = self.m_func(D)
            if self.eps_func != None:
                tm.eps = self.eps_func(D)
            self._m_table[i] = tm.m
            tm.axi = D/2.0
            for geom in self.geometries:
                tm.set_geometry(geom)
                (S, Z) = tm.get_SZ_orient()
                self._S_table[geom][:,:,i] = S
                self._Z_table[geom][:,:,i] = Z

        #restore old values
        (tm.m, tm.eps, tm.axi) = (old_m, old_eps, old_axi) 
        tm.set_geometry(old_geom)


    def save_scatter_table(self, fn, description=""):
        """Save the scattering lookup tables.
        
        Save the state of the scattering lookup tables to a file.
        This can be loaded later with load_scatter_table.

        Other variables will not be saved, but this does not matter because
        the results of the computations are based only on the contents
        of the table.

        Args:
           fn: The name of the scattering table file. 
           description (optional): A description of the table.
        """
        data = {
           "description": description,
           "time": datetime.now(),
           "psd_scatter": (self.num_points, self.D_max, self._psd_D, self._S_table,
                self.Z_table, self._m_table, self.geometries),
           "version": tmatrix_aux.VERSION
           }
        pickle.dump(data, file(fn, 'w'), pickle.HIGHEST_PROTOCOL)


    def load_scatter_table(self, fn):
        """Load the scattering lookup tables.
        
        Load the scattering lookup tables saved with save_scatter_table.

        Args:
            fn: The name of the scattering table file.            
        """
        data = pickle.load(file(fn))

        if ("version" not in data) or (data["version"] != tmatrix_aux.VERSION):
            warnings.warn("Loading data saved with another version.", Warning)

        (self.num_points, self.D_max, self._psd_D, self._S_table, 
            self._Z_table, self._m_table, self.geometries) = data["psd_scatter"]
        return (data["time"], data["description"])
