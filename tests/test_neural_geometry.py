"""Graph invariants matter for rendering, picking and the neuron inspector."""

import json
import math
import unittest

from jarvis.ui.neural_geometry import build_neural_graph


class NeuralGraphTests(unittest.TestCase):
    def test_deterministic_finite_graph_with_two_separate_hemispheres(self):
        graph = build_neural_graph(800)
        self.assertEqual(graph, build_neural_graph(800))
        self.assertEqual(len(graph.positions), 800)
        self.assertEqual(set(graph.hemispheres), {-1, 1})
        for point, side, delay in zip(graph.positions, graph.hemispheres, graph.arrivals):
            self.assertTrue(all(math.isfinite(value) for value in (*point, delay)))
            self.assertGreaterEqual(point[0] * side, 0.045)
            self.assertGreaterEqual(delay, 0)
        json.dumps(graph.payload(), allow_nan=False)

    def test_synapses_are_short_unique_and_have_valid_endpoints(self):
        for count in (400, 2800, 6000):
            with self.subTest(count=count):
                graph = build_neural_graph(count)
                self.assertEqual(len(graph.edges), len(set(graph.edges)))
                maximum = 0.29 * (2800 / count) ** (1 / 3) * 1.28
                degrees = [0] * count
                for a, b in graph.edges:
                    self.assertTrue(0 <= a < b < count)
                    self.assertLess(math.dist(graph.positions[a], graph.positions[b]), maximum)
                    degrees[a] += 1
                    degrees[b] += 1
                self.assertNotIn(0, degrees)

    def test_propagation_delays_follow_graph_distance(self):
        graph = build_neural_graph(1000)
        for a, b in graph.edges:
            self.assertLessEqual(abs(graph.arrivals[a] - graph.arrivals[b]),
                                 math.dist(graph.positions[a], graph.positions[b]) + 0.000003)

    def test_particle_budget_rejects_unbounded_or_invalid_inputs(self):
        for count in (0, 399, 6001, 100000, True, 2800.0, "2800"):
            with self.subTest(count=count), self.assertRaises(ValueError):
                build_neural_graph(count)
