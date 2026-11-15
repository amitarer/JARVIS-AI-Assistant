"""Deterministic cortical graph for the isolated WebGL preview (no AI imports)."""

from dataclasses import dataclass
import heapq
import math
import random


@dataclass(frozen=True)
class NeuralGraph:
    positions: list[list[float]]
    edges: list[tuple[int, int]]
    arrivals: list[float]
    hemispheres: list[int]
    style: str = "cortex"
    filament_count: int = 0

    def payload(self) -> dict:
        return {"positions": self.positions, "edges": self.edges,
                "arrivals": self.arrivals, "hemispheres": self.hemispheres,
                "style": self.style, "filamentCount": self.filament_count}


def build_neural_graph(count: int = 2800) -> NeuralGraph:
    """Folded hemispheres, short synapses and a small callosal bridge.

    A Fibonacci distribution avoids polar clumps. A spatial hash limits neighbor
    searches; paths from bilateral thalamic seeds schedule coherent signal waves.
    The shape is an artistic cortex, not an anatomical or medical model.
    """
    if isinstance(count, bool) or not isinstance(count, int) or not 400 <= count <= 6000:
        raise ValueError("Numero di neuroni consentito: 400–6000.")
    rng = random.Random(704)
    positions, hemispheres = [], []
    golden = math.pi * (3 - math.sqrt(5))
    for index in range(count):
        side = -1 if index % 2 == 0 else 1
        sample, total = index // 2, (count + (side == -1)) // 2
        y = 1 - 2 * (sample + 0.5) / total
        theta = math.acos(y)
        phi = ((sample * golden) % math.tau) - math.pi
        # Fold the sphere onto one hemisphere, preserving an explicit fissure.
        sx = abs(math.sin(theta) * math.cos(phi))
        sz = math.sin(theta) * math.sin(phi)
        fold = (0.078 * math.sin(11 * theta + 2.5 * math.sin(3 * phi))
                + 0.041 * math.sin(16 * phi + 3 * theta)
                + 0.016 * math.sin(26 * theta - 4 * phi))
        radius = 1 + fold
        # Lower temporal lobe narrows toward the brainstem; the frontal pole is fuller.
        width = 0.88 * (1 - 0.23 * max(0, -y)) * (1 + 0.055 * sz)
        cleft = 0.055 + 0.085 * max(0, y) ** 3
        px = side * (cleft + width * sx * radius)
        py = 0.80 * y * (1 - 0.06 * y * y) * radius + 0.11 * sz
        py += 0.15 * (1 - sx) ** 3 * max(0, -y)
        pz = 1.43 * sz * radius
        if index % 9 == 0:
            # A quieter inner network supplies volume without filling the silhouette.
            scale = rng.uniform(0.58, 0.83)
            px = side * (0.045 + (abs(px) - 0.045) * scale)
            py *= scale
            pz *= scale
        positions.append([round(px, 6), round(py, 6), round(pz, 6)])
        hemispheres.append(side)

    cell = 0.29 * (2800 / count) ** (1 / 3)
    buckets = {}
    for index, point in enumerate(positions):
        key = (hemispheres[index], *(math.floor(v / cell) for v in point))
        buckets.setdefault(key, []).append(index)
    edge_set = set()
    for a, point in enumerate(positions):
        grid = [math.floor(v / cell) for v in point]
        candidates = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for dz in (-1, 0, 1):
                    key = (hemispheres[a], grid[0] + dx, grid[1] + dy, grid[2] + dz)
                    for b in buckets.get(key, ()):
                        if a != b:
                            distance = math.dist(point, positions[b])
                            if distance < cell * 1.28:
                                candidates.append((distance, b))
        for _, b in sorted(candidates)[:5]:
            edge_set.add((min(a, b), max(a, b)))
    # Sparse, local interhemispheric communication in the central white matter.
    midline = [i for i, p in enumerate(positions) if abs(p[0]) < 0.16
               and abs(p[1]) < 0.36 and abs(p[2]) < 0.65]
    for a in midline:
        targets = [b for b in midline if hemispheres[b] != hemispheres[a]
                   and math.dist(positions[a], positions[b]) < cell * 1.28]
        if targets:
            b = min(targets, key=lambda b: math.dist(positions[a], positions[b]))
            edge_set.add((min(a, b), max(a, b)))
    edges = sorted(edge_set)
    adjacency = [[] for _ in positions]
    for a, b in edges:
        distance = math.dist(positions[a], positions[b])
        adjacency[a].append((b, distance))
        adjacency[b].append((a, distance))
    arrivals = [math.inf] * count
    # Also seed rare disconnected components; no neuron gets a non-finite delay.
    roots = [min((i for i in range(count) if hemispheres[i] == side),
                 key=lambda i: math.dist(positions[i], (side * 0.22, -0.1, 0)))
             for side in (-1, 1)]
    for root in roots + list(range(count)):
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
    return NeuralGraph(positions, edges, [round(v, 6) for v in arrivals], hemispheres)
