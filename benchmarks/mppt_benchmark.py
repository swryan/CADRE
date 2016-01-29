""" Optimization of the CADRE MDP."""
import timeit
from six.moves import range

import numpy as np

from openmdao.api import IndepVarComp, Component, Group, Problem, ParallelGroup
from openmdao.drivers.pyoptsparse_driver import pyOptSparseDriver

from CADRE.power import Power_SolarPower, Power_CellVoltage
from CADRE.parameters import BsplineParameters

try:
    from openmdao.core.petsc_impl import PetscImpl as impl
except ImportError:
    impl = None

import os
import pickle

class Perf(Component):

  def __init__(self, n):
    super(Perf, self).__init__()
    self.add_param('P_sol1', np.zeros((n, )), units="W",
                        desc="Solar panels power over time")
    self.add_param('P_sol2', np.zeros((n, )), units="W",
                        desc="Solar panels power over time")

    self.add_output("result", 0.0)

    self.J = -np.ones((1, n))

  def solve_nonlinear(self, p, u, r):
    u['result'] = -np.sum(p['P_sol1']) -np.sum(p['P_sol2'])

  def linearize(self, p, u, r):

    return {("result", "P_sol1") : self.J,
            ("result", "P_sol2") : self.J}

class MPPT(Group):

    def __init__(self, LOS, temp, area, m, n):
      super(MPPT, self).__init__()

      params = (("LOS" ,LOS, {"units" : "unitless"}),
                ("temperature" , temp, {"units" : "degK"}),
                ("exposedArea" , area, {"units" : "m**2"}),
                ("CP_Isetpt" , np.zeros((12, m)),  {"units" : "A"}))

      self.add("param", IndepVarComp(params))
      self.add("bspline", BsplineParameters(n, m))
      self.add("voltage", Power_CellVoltage(n))
      self.add("power", Power_SolarPower(n))
      #self.add("perf", Perf(n))

      self.connect("param.LOS", "voltage.LOS")
      self.connect("param.temperature", "voltage.temperature")
      self.connect("param.exposedArea", "voltage.exposedArea")

      self.connect("param.CP_Isetpt", "bspline.CP_Isetpt")
      self.connect("bspline.Isetpt", "voltage.Isetpt")

      self.connect("bspline.Isetpt", "power.Isetpt")
      self.connect("voltage.V_sol", "power.V_sol")

      #self.connect("power.P_sol", "perf.P_sol")


class MPPT_MDP(Group):

  def __init__(self):
    super(MPPT_MDP, self).__init__()
    n = 1500
    m = 300
    fpath = os.path.dirname(os.path.realpath(__file__))
    import CADRE
    cadre_path = os.path.dirname(os.path.realpath(CADRE.__file__))
    data = pickle.load(open(cadre_path + "/test/data1346.pkl", 'rb'))

    # CADRE instances go into a Parallel Group
    para = self.add('parallel', ParallelGroup(), promotes=['*'])

    para.add("pt0", MPPT(data['0:LOS'],
                         data['0:temperature'],
                         data['0:exposedArea'],
                         m, n))
    para.add("pt1", MPPT(data['1:LOS'],
                         data['1:temperature'],
                         data['1:exposedArea'],
                         m, n))

    self.add("perf", Perf(1500))

    self.connect("pt0.power.P_sol", "perf.P_sol1")
    self.connect("pt1.power.P_sol", "perf.P_sol2")


class Time_MPPT:
  def setup(self):
    self.model = Problem(impl=impl)
    self.model.root = MPPT_MDP()

    # add SNOPT driver
    self.model.driver = pyOptSparseDriver()
    self.model.driver.options['optimizer'] = "SNOPT"
    self.model.driver.opt_settings = {'Major optimality tolerance': 1e-3,
                                 'Major feasibility tolerance': 1.0e-5,
                                 'Iterations limit': 500000000,
                                 "New basis file": 10}

    self.model.driver.add_objective("perf.result")
    self.model.driver.add_desvar("pt0.param.CP_Isetpt", lower=0., upper=0.4)
    self.model.driver.add_desvar("pt1.param.CP_Isetpt", lower=0., upper=0.4)
    self.model.setup()

  def time_run(self):
   self.model.run()
