"""Reference-inspired amber core built from continuous folded neural filaments.

This is an artistic graph. It does not expose or represent Qwen's internal units.
No dependency on assistant services, databases, audio capture or random motion.
"""

import heapq
import math

from jarvis.ui.neural_geometry import NeuralGraph


def build_organic_graph(count: int = 4800) -> NeuralGraph:
    if isinstance(count, bool) or not isinstance(count, int) or not 400 <= count <= 6000:
        raise ValueError("Numero di nodi consentito: 400–6000.")
    positions, sectors, filament_edges = [], [], set()
    filaments = max(16, min(90, count // 64))
    for fiber in range(filaments):
        samples = count // filaments + (fiber < count % filaments)
        theta_base = math.acos(1 - 2 * (fiber + 0.5) / filaments)
        phase = fiber * math.pi * (3 - math.sqrt(5))
        start = len(positions)
        for step in range(samples):
            u = math.tau * step / samples
            phi = u + phase
            theta = theta_base + math.sin(theta_base) * (
                0.21 * math.sin(3 * u + phase) + 0.08 * math.sin(5 * u - phase))
            radius = (1 + 0.16 * math.sin(3 * phi + 2 * theta)
                      + 0.10 * math.cos(5 * theta - 2 * phi)
                      + 0.065 * math.sin(4 * phi - theta))
            radius *= 0.73 if fiber % 7 == 0 else 1 + 0.018 * math.sin(phase)
            point = [1.04 * radius * math.sin(theta) * math.cos(phi),
                     0.97 * radius * math.cos(theta),
                     0.94 * radius * math.sin(theta) * math.sin(phi)]
            positions.append([round(value, 6) for value in point])
            sectors.append(-1 if point[0] < 0 else 1)
            if step:
                filament_edges.add((len(positions) - 2, len(positions) - 1))
        filament_edges.add((start, len(positions) - 1))

    cell = 0.25 * (4800 / count) ** (1 / 3)
    maximum = cell * 1.45
    edges = {edge for edge in filament_edges if math.dist(positions[edge[0]], positions[edge[1]]) < maximum}
    buckets = {}
    for index, point in enumerate(positions):
        key = tuple(math.floor(value / cell) for value in point)
        buckets.setdefault(key, []).append(index)
    for a, point in enumerate(positions):
        key = [math.floor(value / cell) for value in point]
        candidates = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    for b in buckets.get((key[0] + dx, key[1] + dy, key[2] + dz), ()):
                        if a != b:
                            distance = math.dist(point, positions[b])
                            if distance < maximum:
                                candidates.append((distance, b))
        for _, b in sorted(candidates)[:3]:
            edges.add((min(a, b), max(a, b)))
    edges = sorted(edges)
    adjacency = [[] for _ in positions]
    for a, b in edges:
        cost = math.dist(positions[a], positions[b])
        adjacency[a].append((b, cost))
        adjacency[b].append((a, cost))
    arrivals = [math.inf] * count
    source = min(range(count), key=lambda i: math.dist(positions[i], (0, -0.1, 0.7)))
    for root in [source, *range(count)]:
        if math.isfinite(arrivals[root]):
            continue
        arrivals[root] = 0
        queue = [(0.0, root)]
        while queue:
            distance, a = heapq.heappop(queue)
            if distance > arrivals[a]:
                continue
            for b, cost in adjacency[a]:
                candidate = distance + cost
                if candidate < arrivals[b]:
                    arrivals[b] = candidate
                    heapq.heappush(queue, (candidate, b))
    return NeuralGraph(positions, edges, [round(value, 6) for value in arrivals], sectors,
                       style="organic", filament_count=filaments)
