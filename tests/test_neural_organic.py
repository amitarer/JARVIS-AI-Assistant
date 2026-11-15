"""Actual filament graph invariants, not a screenshot simulation of a network."""

import json
import math
import unittest

from jarvis.ui.neural_organic import build_organic_graph


class OrganicGraphTests(unittest.TestCase):
    def test_repeatable_graph_and_reference_style(self):
        graph = build_organic_graph(1200)
        self.assertEqual(graph, build_organic_graph(1200))
        self.assertEqual(graph.style, "organic")
        self.assertGreaterEqual(graph.filament_count, 16)
        self.assertEqual(len(graph.positions), 1200)
        self.assertEqual(graph.payload()["filamentCount"], graph.filament_count)
        json.dumps(graph.payload(), allow_nan=False)

    def test_local_edges_and_actual_graph_propagation(self):
        for count in (400, 4800, 6000):
            with self.subTest(count=count):
                graph = build_organic_graph(count)
                maximum = 0.25 * (4800 / count) ** (1 / 3) * 1.45
                degrees = [0] * count
                self.assertEqual(len(graph.edges), len(set(graph.edges)))
                for a, b in graph.edges:
                    self.assertTrue(0 <= a < b < count)
                    distance = math.dist(graph.positions[a], graph.positions[b])
                    self.assertLess(distance, maximum)
                    self.assertLessEqual(abs(graph.arrivals[a] - graph.arrivals[b]), distance + 0.000003)
                    degrees[a] += 1
                    degrees[b] += 1
                self.assertNotIn(0, degrees)

    def test_shape_has_volume_and_irregular_radius(self):
        graph = build_organic_graph()
        for axis in range(3):
            values = [point[axis] for point in graph.positions]
            self.assertGreater(max(values) - min(values), 1.5)
        radii = [math.sqrt(sum(value * value for value in p)) for p in graph.positions]
        self.assertGreater(max(radii) - min(radii), 0.5)

    def test_invalid_budgets_are_rejected(self):
        for value in (True, 399, 6001, 4800.0, "4800"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                build_organic_graph(value)
