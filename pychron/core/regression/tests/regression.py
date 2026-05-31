# ===============================================================================
# Copyright 2012 Jake Ross
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ===============================================================================

# ============= enthought library imports =======================

# ============= standard library imports ========================
from unittest import TestCase

from numpy import linspace, polyval

# ============= local library imports  ==========================
from pychron.core.regression.least_squares_regressor import ExponentialRegressor
from pychron.core.regression.mean_regressor import (
    MeanRegressor,
)  # , WeightedMeanRegressor
from pychron.core.regression.new_york_regressor import (
    ReedYorkRegressor,
    NewYorkRegressor,
)
from pychron.core.regression.ols_regressor import OLSRegressor
from pychron.core.regression.flux_regressor import (
    Bracketing1DRegressor,
    NearestNeighborFluxRegressor,
)

# from pychron.core.regression.york_regressor import YorkRegressor
from pychron.core.regression.tests.standard_data import (
    mean_data,
    filter_data,
    ols_data,
    pearson,
    pre_truncated_data,
    expo_data,
    expo_data_linear,
)


class RegressionTestCase(object):
    @classmethod
    def setUpClass(cls):
        cls.reg = cls.reg_klass()

    def testN(self):
        self.assertEqual(self.reg.n, self.solution["n"])


class TruncateRegressionTest(TestCase):
    def setUp(self):
        self.reg = MeanRegressor()

    def test_pre_truncate(self):
        xs, ys, sol = pre_truncated_data()
        self.reg.trait_set(xs=xs, ys=ys)
        self.solution = sol
        self.reg.trait_set(xs=xs, ys=ys)
        self.reg.set_truncate("x<5")

        self.assertEqual(self.reg.mean, self.solution["pre_mean"])

    def test_post_truncate(self):
        xs, ys, sol = pre_truncated_data()
        self.reg.trait_set(xs=xs, ys=ys)
        self.solution = sol
        self.reg.trait_set(xs=xs, ys=ys)
        self.reg.set_truncate("x>=5")

        self.assertEqual(self.reg.mean, self.solution["post_mean"])


class MeanRegressionTest(RegressionTestCase, TestCase):
    reg_klass = MeanRegressor

    def setUp(self):
        n = 1e5
        xs, ys, sol = mean_data(n=n)
        self.reg.trait_set(xs=xs, ys=ys)
        self.solution = sol

    def testMean(self):
        self.assertAlmostEqual(self.reg.mean, self.solution["mean"], 2)

    def testStd(self):
        self.assertAlmostEqual(self.reg.std, self.solution["std"], 2)


class OLSRegressionTest(RegressionTestCase, TestCase):
    reg_klass = OLSRegressor

    def setUp(self):
        xs, ys, sol = ols_data()
        self.reg.trait_set(xs=xs, ys=ys, fit="linear")
        self.solution = sol
        self.reg.calculate()

    def testSlope(self):
        cs = self.reg.coefficients
        self.assertAlmostEqual(cs[-1], self.solution["slope"], 4)

    def testYIntercept(self):
        cs = self.reg.coefficients
        self.assertAlmostEqual(cs[0], self.solution["y_intercept"], 4)

    def testPredictErrorSEM(self):
        e = self.reg.predict_error(self.solution["pred_x"], error_calc="SEM")
        self.assertAlmostEqual(e, self.solution["pred_error"], 3)


class OLSRegressionTest2(RegressionTestCase, TestCase):
    reg_klass = OLSRegressor

    def setUp(self):
        n = 100
        coeffs = [2.12, 1.13, 5.14]
        xs = linspace(0, 100, n)
        ys = polyval(coeffs, xs)

        self.reg.trait_set(xs=xs, ys=ys, fit="parabolic")

        sol = {"coefficients": coeffs, "n": n}
        self.solution = sol
        self.reg.calculate()

    def testcoefficients(self):
        self.assertListEqual(
            list([round(x, 6) for x in self.reg.coefficients[::-1]]),
            self.solution["coefficients"],
        )


class FilterOLSRegressionTest(RegressionTestCase, TestCase):
    reg_klass = OLSRegressor

    def setUp(self):
        xs, ys, sol = filter_data()
        self.reg.trait_set(
            xs=xs,
            ys=ys,
            fit="linear",
            filter_outliers_dict={
                "filter_outliers": True,
                "iterations": 1,
                "std_devs": 2,
            },
        )
        self.solution = sol
        self.reg.calculate()

    def testSlope(self):
        cs = self.reg.coefficients
        self.assertAlmostEqual(cs[-1], self.solution["slope"], 4)

    def testYIntercept(self):
        cs = self.reg.coefficients
        self.assertAlmostEqual(cs[0], self.solution["y_intercept"], 4)

    def testPredictErrorSEM(self):
        e = self.reg.predict_error(self.solution["pred_x"], error_calc="SEM")
        # e=self.reg.coefficient_errors[0]
        self.assertAlmostEqual(e, self.solution["pred_error"], 3)


class PearsonRegressionTest(RegressionTestCase):
    kind = ""

    def setUp(self):
        xs, ys, wxs, wys = pearson()

        exs = wxs**-0.5
        eys = wys**-0.5

        self.reg.trait_set(xs=xs, ys=ys, xserr=exs, yserr=eys, error_calc_type="SE")
        self.reg.calculate()
        self.solution = {"n": len(xs)}

    def test_slope(self):
        exp = pearson(self.kind)
        self.assertAlmostEqual(self.reg.slope, exp["slope"], 4)

    def test_slope_err(self):
        exp = pearson(self.kind)
        self.assertAlmostEqual(self.reg.get_slope_variance() ** 0.5, exp["slope_err"], 4)

    def test_y_intercept(self):
        expected = pearson(self.kind)
        self.assertAlmostEqual(self.reg.intercept, expected["intercept"], 4)

    def test_y_intercept_error(self):
        expected = pearson(self.kind)
        self.assertAlmostEqual(self.reg.get_intercept_error(), expected["intercept_err"], 4)

    def test_mswd(self):
        expected = pearson(self.kind)
        self.assertAlmostEqual(self.reg.mswd, expected["mswd"], 3)


class ReedRegressionTest(PearsonRegressionTest, TestCase):
    reg_klass = ReedYorkRegressor
    kind = "reed"


class NewYorkRegressionTest(PearsonRegressionTest, TestCase):
    reg_klass = NewYorkRegressor
    kind = "new_york"
    # def test_llnl(self):
    #     self.assertEqual(self.reg.get_slope_variance(), self.reg.test_llnl())
    # def test_llnl_vs_pychron_mahon(self):
    #     self.assertEqual(self.reg.get_slope_variance_llnl(), self.reg.get_slope_variance_pychron())


class ExpoRegressionTest(TestCase):
    def setUp(self):
        xs, ys, sol = expo_data()
        self.reg = ExponentialRegressor(xs=xs, ys=ys)
        self.solution = sol

    def test_a(self):
        self.reg.calculate()
        self.assertAlmostEqual(self.reg.coefficients[0], self.solution["coefficients"][0])

    def test_b(self):
        self.reg.calculate()
        self.assertAlmostEqual(self.reg.coefficients[1], self.solution["coefficients"][1])

    def test_c(self):
        self.reg.calculate()
        self.assertAlmostEqual(self.reg.coefficients[2], self.solution["coefficients"][2])


class ExpoRegressionTest2(TestCase):
    def setUp(self):
        xs, ys, sol = expo_data_linear()
        self.reg = ExponentialRegressor(xs=xs, ys=ys)
        self.solution = sol

    def test_c(self):
        self.reg.calculate()
        self.assertAlmostEqual(self.reg.coefficients[2], self.solution["coefficients"][2], places=5)


class NearestNeighborLinearTest(TestCase):
    """2-D bracketing (NN n=2, LINEAR): projection fraction + quadrature error."""

    def setUp(self):
        from numpy import array
        from pychron.pychron_constants import LINEAR

        self.reg = NearestNeighborFluxRegressor(
            xs=array([[0.0, 0.0], [10.0, 0.0]]),
            ys=array([1.0, 2.0]),
            yserr=array([0.1, 0.2]),
            n=2,
            interpolation_style=LINEAR,
        )
        self.reg.calculate()

    def test_midpoint_value(self):
        from numpy import array

        self.assertAlmostEqual(self.reg.predict(array([[5.0, 0.0]]))[0], 1.5, 6)

    def test_error_quadrature(self):
        from numpy import array

        expected = (((0.5 * 0.1) ** 2) + ((0.5 * 0.2) ** 2)) ** 0.5
        self.assertAlmostEqual(self.reg.predict_error(array([[5.0, 0.0]]))[0], expected, 9)

    def test_offline_projection(self):
        from numpy import array

        # an unknown off the monitor line still projects to f=0.5
        self.assertAlmostEqual(self.reg.predict(array([[5.0, 3.0]]))[0], 1.5, 6)


class NearestNeighborLinearNGT2Test(TestCase):
    """NN LINEAR with n>2 must interpolate between the two NEAREST monitors.

    With n=4 the n-nearest set is index-sorted, so the old code used the
    index-extreme pair (here x=0 and x=30) and ignored the middle monitors.
    The fix interpolates between the two closest monitors regardless of n.
    """

    def setUp(self):
        from numpy import array
        from pychron.pychron_constants import LINEAR

        self.reg = NearestNeighborFluxRegressor(
            xs=array([[0.0, 0.0], [10.0, 0.0], [20.0, 0.0], [30.0, 0.0]]),
            ys=array([1.0, 2.0, 4.0, 8.0]),
            yserr=array([0.1, 0.2, 0.4, 0.8]),
            n=4,
            interpolation_style=LINEAR,
        )
        self.reg.calculate()

    def test_uses_two_nearest_not_index_extremes(self):
        from numpy import array

        # x=12 -> two nearest are x=10 (J=2) and x=20 (J=4); f=0.2 -> 2.4.
        # If index-extremes (x=0,x=30) were used the result would differ.
        self.assertAlmostEqual(self.reg.predict(array([[12.0, 0.0]]))[0], 2.4, 6)

    def test_error_uses_two_nearest(self):
        from numpy import array

        # nearest errors 0.2, 0.4 at f=0.2
        expected = (((0.8 * 0.2) ** 2) + ((0.2 * 0.4) ** 2)) ** 0.5
        self.assertAlmostEqual(self.reg.predict_error(array([[12.0, 0.0]]))[0], expected, 9)

    def test_two_nearest_indices(self):
        i0, i1 = self.reg._two_nearest(12.0, 0.0)
        self.assertEqual({int(i0), int(i1)}, {1, 2})


# ============= EOF =============================================

# class WeightedMeanRegressionTest(RegressionTestCase, TestCase):
#     @staticmethod
#     def regressor_factory():
#         return WeightedMeanRegressor()
#
#     def setUp(self):
#         xs, ys, yes, sol = weighted_mean_data()
#         self.reg.trait_set(xs=xs, ys=ys,
#                            yserr=yes,
#         )
#         self.solution = sol
#         self.reg.calculate()
#
#     def testMean(self):
#         v = self.reg.mean
#         self.assertEqual(v, self.solution['mean'])


# class WeightedMeanRegressionTest(TestCase):
#     def setUp(self):
#         n = 1000
#         ys = np.ones(n) * 5
#         #        es = np.random.rand(n)
#         es = np.ones(n)
#         ys = np.hstack((ys, [5.1]))
#         es = np.hstack((es, [1000]))
# #        print 'exception', es
#         self.reg = WeightedMeanRegressor(ys=ys, errors=es)

#    def testMean(self):
#        m = self.reg.mean
#        self.assertEqual(m, 5)

# class RegressionTest(TestCase):
#     def setUp(self):
#         self.x = np.array([1, 2, 3, 4, 4, 5, 5, 6, 6, 7])
#         self.y = np.array([7, 8, 9, 8, 9, 11, 10, 13, 14, 13])
#
#     def testMeans(self):
#         xm = self.x.mean()
#         ym = self.y.mean()
#         self.assertEqual(xm, 4.3)
#         self.assertEqual(ym, 10.2)
#
#
# class CITest(TestCase):
#     def setUp(self):
#         self.x = np.array([0, 12, 29.5, 43, 53, 62.5, 75.5, 85, 93])
#         self.y = np.array([8.98, 8.14, 6.67, 6.08, 5.9, 5.83, 4.68, 4.2, 3.72])
#
#     def testUpper(self):
#         reg = PolynomialRegressor(xs=self.x, ys=self.y, degree=1)
#         l, u = reg.calculate_ci([0, 10, 100])
#         for ui, ti in zip(u, [9.16, 8.56, 3.83]):
#             self.assertAlmostEqual(ui, ti, delta=0.01)
#
#     def testLower(self):
#         reg = PolynomialRegressor(xs=self.x, ys=self.y, degree=1)
#         l, u = reg.calculate_ci([0])
#
#         self.assertAlmostEqual(l[0], 8.25, delta=0.01)
#
#     def testSYX(self):
#         reg = PolynomialRegressor(xs=self.x, ys=self.y, degree=1)
#         self.assertAlmostEqual(reg.get_syx(), 0.297, delta=0.01)
#
#     def testSSX(self):
#         reg = PolynomialRegressor(xs=self.x, ys=self.y, degree=1)
#         self.assertAlmostEqual(reg.get_ssx(), 8301.389, delta=0.01)


# class WLSRegressionTest(TestCase):
#     def setUp(self):
#         self.xs = np.linspace(0, 10, 10)
#         self.ys = np.random.normal(self.xs, 1)
#
#         '''
#             draper and smith p.8
#         '''
#         self.xs = [35.3, 29.7, 30.8, 58.8, 61.4, 71.3, 74.4, 76.7, 70.7, 57.5,
#                    46.4, 28.9, 28.1, 39.1, 46.8, 48.5, 59.3, 70, 70, 74.5, 72.1,
#                    58.1, 44.6, 33.4, 28.6
#         ]
#         self.ys = [10.98, 11.13, 12.51, 8.4, 9.27, 8.73, 6.36, 8.50,
#                    7.82, 9.14, 8.24, 12.19, 11.88, 9.57, 10.94, 9.58,
#                    10.09, 8.11, 6.83, 8.88, 7.68, 8.47, 8.86, 10.36, 11.08
#         ]
#         self.es = np.random.normal(1, 0.5, len(self.xs))
#
#         self.slope = -0.0798
#         self.intercept = 13.623
#         self.Xk = 28.6
#         self.ypred_k = 0.3091
#         xs = self.xs
#         ys = self.ys
#         es = self.es
#         self.wls = WeightedPolynomialRegressor(xs=xs, ys=ys,
#                                                yserr=es, fit='linear')
#
#     def testVarCovar(self):
#         wls = self.wls
#         cv = wls.var_covar
#         print cv
#         print wls._result.normalized_cov_params
#
#     #        print wls._result.cov_params()


# class OLSRegressionTest(TestCase):
#     def setUp(self):
#         self.xs = np.linspace(0, 10, 10)
#         #        self.ys = np.random.normal(self.xs, 1)
#         #        print self.ys
#         self.ys = [-1.8593967, 3.15506254, 1.82144207, 4.58729807, 4.95813564,
#                    5.71229382, 7.04611731, 8.14459843, 10.27429285, 10.10989719]
#
#         '''
#             draper and smith p.8
#         '''
#         self.xs = [35.3, 29.7, 30.8, 58.8, 61.4, 71.3, 74.4, 76.7, 70.7, 57.5,
#                    46.4, 28.9, 28.1, 39.1, 46.8, 48.5, 59.3, 70, 70, 74.5, 72.1,
#                    58.1, 44.6, 33.4, 28.6
#         ]
#         self.ys = [10.98, 11.13, 12.51, 8.4, 9.27, 8.73, 6.36, 8.50,
#                    7.82, 9.14, 8.24, 12.19, 11.88, 9.57, 10.94, 9.58,
#                    10.09, 8.11, 6.83, 8.88, 7.68, 8.47, 8.86, 10.36, 11.08
#         ]
#
#         self.slope = -0.0798
#         self.intercept = 13.623
#         self.Xk = 28.6
#         self.ypred_k = 0.3091
#         xs = self.xs
#         ys = self.ys
#         ols = PolynomialRegressor(xs=xs, ys=ys, fit='linear')
#
#         self.ols = ols
#
#     def testSlope(self):
#         ols = self.ols
#         b, s = ols.coefficients
#         self.assertAlmostEqual(s, self.slope, 4)
#
#     def testIntercept(self):
#         ols = self.ols
#         b, s = ols.coefficients
#         self.assertAlmostEqual(b, self.intercept, 4)
#         self.assertAlmostEqual(ols.predict(0), self.intercept, 4)
#
#     def testPredictYerr(self):
#         ols = self.ols
#         ypred = ols.predict_error(self.Xk, error_calc='SEM')
#         self.assertAlmostEqual(ypred, self.ypred_k, 3)
#
#     def testPredictYerr_matrix(self):
#         ols = self.ols
#         ypred = ols.predict_error_matrix([self.Xk])[0]
#         self.assertAlmostEqual(ypred, self.ypred_k, 3)
#
#     def testPredictYerr_al(self):
#         ols = self.ols
#         ypred = ols.predict_error_al(self.Xk)[0]
#         self.assertAlmostEqual(ypred, self.ypred_k, 3)
#
#     def testPredictYerrSD(self):
#         ols = self.ols
#         ypred = ols.predict_error(self.Xk, error_calc='SEM')
#         ypredm = ols.predict_error_matrix([self.Xk], error_calc='SEM')[0]
#         self.assertAlmostEqual(ypred, ypredm, 7)
#
#     def testPredictYerrSD_al(self):
#         ols = self.ols
#         ypred = ols.predict_error(self.Xk, error_calc='sd')
#         ypredal = ols.predict_error_al(self.Xk, error_calc='sd')[0]
#         self.assertAlmostEqual(ypred, ypredal, 7)

#    def testCovar(self):
#        ols = self.ols
#        cv = ols.calculate_var_covar()
#        self.assertEqual(cv, cvm)

#    def testCovar(self):
#        ols = self.ols
#        covar = ols.calculate_var_covar()
#        print covar
#        print
#        assert np.array_equal(covar,)

#        print covar
#        print ols._result.cov_params()
#        print ols._result.normalized_cov_params
#    def testPredictYerr2(self):
#        xs = self.xs
#        ys = self.ys
#
#        ols = PolynomialRegressor(xs=xs, ys=ys, fit='parabolic')
#        y = ols.predict_error(5)[0]
# #        yal = ols.predict_error_al(5)[0]
# #        print y, yal
#        self.assertEqual(y, self.Yprederr_5_parabolic)
# #        self.assertEqual(yal, self.Yprederr_5_parabolic)


class Bracketing1DRegressionTest(TestCase):
    """Lever-rule 1-D bracketing: interpolation, quadrature error, extrapolation."""

    def setUp(self):
        from numpy import array

        # monitors along a single axis
        self.xs = array([0.0, 10.0, 20.0])
        self.ys = array([1.0, 2.0, 4.0])
        self.es = array([0.1, 0.2, 0.4])
        self.reg = Bracketing1DRegressor()
        self.reg.trait_set(xs=self.xs, ys=self.ys, yserr=self.es)
        self.reg.calculate()

    def _predict(self, p):
        from numpy import array

        return self.reg.predict(array([p]))[0]

    def _predict_error(self, p):
        from numpy import array

        return self.reg.predict_error(array([p]))[0]

    def test_interpolate_midpoint(self):
        # f=0.5 between (0,1) and (10,2)
        self.assertAlmostEqual(self._predict(5.0), 1.5, 6)

    def test_interpolate_quarter(self):
        # f=0.25 between (0,1) and (10,2)
        self.assertAlmostEqual(self._predict(2.5), 1.25, 6)

    def test_error_quadrature(self):
        # sqrt(((1-0.5)*0.1)^2 + (0.5*0.2)^2)
        expected = (((0.5 * 0.1) ** 2) + ((0.5 * 0.2) ** 2)) ** 0.5
        self.assertAlmostEqual(self._predict_error(5.0), expected, 9)

    def test_exact_on_node(self):
        self.assertAlmostEqual(self._predict(10.0), 2.0, 6)
        self.assertAlmostEqual(self._predict(0.0), 1.0, 6)
        self.assertAlmostEqual(self._predict(20.0), 4.0, 6)

    def test_extrapolate_below(self):
        # below range uses pair (0,10): f=-1 -> 1 + (-1)*(2-1) = 0
        self.assertAlmostEqual(self._predict(-10.0), 0.0, 6)

    def test_extrapolate_above(self):
        # above range uses pair (10,20): f=2 -> 2 + 2*(4-2) = 6
        self.assertAlmostEqual(self._predict(30.0), 6.0, 6)

    def test_unsorted_input(self):
        from numpy import array

        reg = Bracketing1DRegressor(
            xs=array([20.0, 0.0, 10.0]),
            ys=array([4.0, 1.0, 2.0]),
            yserr=array([0.4, 0.1, 0.2]),
        )
        reg.calculate()
        self.assertAlmostEqual(reg.predict(array([5.0]))[0], 1.5, 6)

    def test_set_neighbors(self):
        class P:
            def __init__(self, x, hid):
                self.x = x
                self.y = 0.0
                self.hole_id = hid
                self.bracket_a = None
                self.bracket_b = None

        mons = [P(0.0, "m0"), P(10.0, "m1"), P(20.0, "m2")]
        reg = Bracketing1DRegressor(xs=self.xs, ys=self.ys, yserr=self.es, one_d_axis="X")
        reg.calculate()
        unk = P(5.0, "u0")
        reg.set_neighbors([unk], mons)
        self.assertEqual(unk.bracket_a, "m0")
        self.assertEqual(unk.bracket_b, "m1")


# ---- tube (1-D vertical) irradiation geometry ---------------------------------
# Holder file format (pychron.dvc.meta_object.IrradiationGeometry):
#   header  "count,default_radius"
#   then    "x,y,r" per hole  -> holes = [(x, y, r, hole_id), ...]
# A "tube" stacks all holes along Y at x=0 with unit spacing (y = 0..49).
TUBE_GEOM_TEXT = "50,0.0175\n" + "\n".join("0.0000,{:.4f},1.0000".format(i) for i in range(50))


def _load_tube_geometry():
    import os
    import tempfile

    from pychron.dvc.meta_object import IrradiationGeometry

    fd, p = tempfile.mkstemp(suffix=".txt")
    try:
        os.write(fd, TUBE_GEOM_TEXT.encode())
        os.close(fd)
        return IrradiationGeometry(p).holes
    finally:
        os.remove(p)


class TubeGeometryParseTest(TestCase):
    """Parse a tube holder file via IrradiationGeometry."""

    def setUp(self):
        self.holes = _load_tube_geometry()

    def test_count(self):
        self.assertEqual(len(self.holes), 50)

    def test_tuple_shape(self):
        # (x, y, r, hole_id) with hole_id a string
        x, y, r, hid = self.holes[0]
        self.assertEqual((x, y, r, hid), (0.0, 0.0, 1.0, "1"))

    def test_x_all_zero(self):
        self.assertTrue(all(h[0] == 0.0 for h in self.holes))

    def test_y_monotonic_unit_spacing(self):
        ys = [h[1] for h in self.holes]
        self.assertEqual(ys, [float(i) for i in range(50)])
        self.assertTrue(all((b - a) == 1.0 for a, b in zip(ys, ys[1:])))

    def test_hole_ids(self):
        self.assertEqual([h[3] for h in self.holes], [str(i) for i in range(1, 51)])


class TubeGeometryFluxTest(TestCase):
    """Flux fitting/plotting for the 1-D 'tube' geometry.

    Monitors are a subset of holes; J varies linearly with height
    J(y) = j0 + slope * y. Bracketing1D with one_d_axis='Y' must recover it
    by lever-rule interpolation, including linear extrapolation above the
    topmost monitor.
    """

    def setUp(self):
        from numpy import array

        self.holes = _load_tube_geometry()

        self.j0 = 1.0e-4
        self.slope = 1.0e-6

        # every 10th hole is a monitor: y = 0, 10, 20, 30, 40
        mons = self.holes[::10]
        self.mon_y = array([h[1] for h in mons])
        self.mon_j = array([self.j0 + self.slope * h[1] for h in mons])
        self.mon_e = array([1.0e-7] * len(mons))

        self.reg = Bracketing1DRegressor()
        self.reg.trait_set(xs=self.mon_y, ys=self.mon_j, yserr=self.mon_e, one_d_axis="Y")
        self.reg.calculate()

    def _predict(self, y):
        from numpy import array

        return self.reg.predict(array([y]))[0]

    def _expected(self, y):
        return self.j0 + self.slope * y

    def test_interpolate_between_monitors(self):
        # midway between monitors at y=10 and y=20
        self.assertAlmostEqual(self._predict(15.0), self._expected(15.0), 12)

    def test_exact_on_monitor(self):
        self.assertAlmostEqual(self._predict(20.0), self.mon_j[2], 12)

    def test_every_hole_on_gradient(self):
        # every hole (interp + the extrapolated tail above y=40) lies on J(y)
        for h in self.holes:
            y = h[1]
            self.assertAlmostEqual(self._predict(y), self._expected(y), 12)

    def test_extrapolate_above_top_monitor(self):
        # holes above the last monitor (y=40) extrapolate along the gradient
        self.assertAlmostEqual(self._predict(49.0), self._expected(49.0), 12)

    def test_error_quadrature_midpoint(self):
        from numpy import array

        e = self.reg.predict_error(array([15.0]))[0]
        expected = (((0.5 * 1.0e-7) ** 2) + ((0.5 * 1.0e-7) ** 2)) ** 0.5
        self.assertAlmostEqual(e, expected, 15)

    def test_set_neighbors_brackets(self):
        class P:
            bracket_a: object = None
            bracket_b: object = None

            def __init__(self, y, hid):
                self.x = 0.0
                self.y = y
                self.hole_id = hid

        mons = [P(y, "m{}".format(int(y))) for y in self.mon_y]
        unk = P(15.0, "u15")
        self.reg.set_neighbors([unk], mons)
        self.assertEqual(unk.bracket_a, "m10")
        self.assertEqual(unk.bracket_b, "m20")

    def test_predicted_curve_increasing(self):
        from numpy import array

        ys = array([h[1] for h in self.holes])
        js = self.reg.predict(ys)
        # rising gradient -> predicted J strictly increases up the tube
        self.assertTrue(all(b > a for a, b in zip(js, js[1:])))
