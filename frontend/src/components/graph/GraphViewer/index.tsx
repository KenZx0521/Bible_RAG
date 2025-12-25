/**
 * GraphViewer Component
 *
 * D3.js-based knowledge graph visualization component.
 * Displays nodes and edges with force-directed layout.
 *
 * Features:
 * - Force simulation with link, charge, center, and collision forces
 * - Node colors by type (Person, Place, Group, Event, Topic)
 * - Center node emphasis
 * - Node dragging
 * - Click to select nodes
 * - Hover tooltips
 * - Zoom and pan
 * - Legend display
 *
 * @example
 * <GraphViewer
 *   nodes={nodes}
 *   edges={edges}
 *   centerNodeId="person_1"
 *   onNodeClick={(node) => console.log('Clicked:', node)}
 * />
 */

import { useEffect, useRef, useCallback, useState } from 'react';
import * as d3 from 'd3';
import { cn } from '@/lib/utils';
import type { GraphNode, GraphEdge } from '@/types';

// =============================================================================
// Types
// =============================================================================

export interface GraphViewerProps {
  /** Nodes to display */
  nodes: GraphNode[];
  /** Edges connecting nodes */
  edges: GraphEdge[];
  /** Optional node click handler */
  onNodeClick?: (node: GraphNode) => void;
  /** ID of the center node (will be enlarged) */
  centerNodeId?: string;
  /** Container width (default: 100%) */
  width?: number | string;
  /** Container height (default: 500) */
  height?: number;
  /** Additional class name */
  className?: string;
}

/** Internal node type with D3 simulation properties */
interface SimulationNode extends GraphNode {
  x?: number;
  y?: number;
  fx?: number | null;
  fy?: number | null;
}

/** Internal edge type with D3 simulation properties */
interface SimulationEdge {
  source: SimulationNode | string;
  target: SimulationNode | string;
  type: string;
  properties: Record<string, unknown>;
}

// =============================================================================
// Constants
// =============================================================================

/** Node colors by type */
const NODE_COLORS: Record<string, string> = {
  PERSON: '#E57373', // Red
  PLACE: '#64B5F6', // Blue
  GROUP: '#BA68C8', // Purple
  EVENT: '#FFB74D', // Orange
  TOPIC: '#81C784', // Green
  DEFAULT: '#90A4AE', // Gray
};

/** Legend items */
const LEGEND_ITEMS = [
  { type: 'PERSON', label: '人物', color: '#E57373' },
  { type: 'PLACE', label: '地點', color: '#64B5F6' },
  { type: 'GROUP', label: '群體', color: '#BA68C8' },
  { type: 'EVENT', label: '事件', color: '#FFB74D' },
  { type: 'TOPIC', label: '主題', color: '#81C784' },
];

// =============================================================================
// Component
// =============================================================================

export function GraphViewer({
  nodes,
  edges,
  onNodeClick,
  centerNodeId,
  width = '100%',
  height = 500,
  className,
}: GraphViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const simulationRef = useRef<d3.Simulation<SimulationNode, SimulationEdge> | null>(null);
  const [dimensions, setDimensions] = useState({ width: 800, height: 500 });
  const [hoveredNode, setHoveredNode] = useState<SimulationNode | null>(null);

  // Update dimensions on resize
  useEffect(() => {
    const updateDimensions = () => {
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        setDimensions({
          width: rect.width || 800,
          height: typeof height === 'number' ? height : 500,
        });
      }
    };

    updateDimensions();
    window.addEventListener('resize', updateDimensions);
    return () => window.removeEventListener('resize', updateDimensions);
  }, [height]);

  // Get node color based on type
  const getNodeColor = useCallback((type: string) => {
    return NODE_COLORS[type.toUpperCase()] || NODE_COLORS.DEFAULT;
  }, []);

  // Get node radius based on whether it's the center node
  const getNodeRadius = useCallback(
    (nodeId: string) => {
      return nodeId === centerNodeId ? 28 : 20;
    },
    [centerNodeId]
  );

  // Initialize D3 visualization
  useEffect(() => {
    if (!svgRef.current || nodes.length === 0) return;

    const svg = d3.select(svgRef.current);
    const { width: svgWidth, height: svgHeight } = dimensions;

    // Clear existing content
    svg.selectAll('*').remove();

    // Create zoom behavior
    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on('zoom', (event) => {
        container.attr('transform', event.transform);
      });

    svg.call(zoom);

    // Create container for zoom/pan
    const container = svg.append('g').attr('class', 'graph-container');

    // Create arrow marker for directed edges
    svg
      .append('defs')
      .append('marker')
      .attr('id', 'arrowhead')
      .attr('viewBox', '-0 -5 10 10')
      .attr('refX', 25)
      .attr('refY', 0)
      .attr('orient', 'auto')
      .attr('markerWidth', 6)
      .attr('markerHeight', 6)
      .attr('xoverflow', 'visible')
      .append('svg:path')
      .attr('d', 'M 0,-5 L 10 ,0 L 0,5')
      .attr('fill', '#9CA3AF')
      .style('stroke', 'none');

    // Prepare simulation data
    const simulationNodes: SimulationNode[] = nodes.map((node) => ({
      ...node,
      x: undefined,
      y: undefined,
      fx: null,
      fy: null,
    }));

    const simulationEdges: SimulationEdge[] = edges.map((edge) => ({
      source: edge.source,
      target: edge.target,
      type: edge.type,
      properties: edge.properties,
    }));

    // Create force simulation
    const simulation = d3
      .forceSimulation<SimulationNode>(simulationNodes)
      .force(
        'link',
        d3
          .forceLink<SimulationNode, SimulationEdge>(simulationEdges)
          .id((d) => d.id)
          .distance(120)
          .strength(0.5)
      )
      .force('charge', d3.forceManyBody().strength(-400))
      .force('center', d3.forceCenter(svgWidth / 2, svgHeight / 2))
      .force('collision', d3.forceCollide<SimulationNode>().radius((d) => getNodeRadius(d.id) + 5))
      .force('x', d3.forceX(svgWidth / 2).strength(0.05))
      .force('y', d3.forceY(svgHeight / 2).strength(0.05));

    simulationRef.current = simulation;

    // Create links
    const link = container
      .append('g')
      .attr('class', 'links')
      .selectAll('line')
      .data(simulationEdges)
      .join('line')
      .attr('class', 'link')
      .attr('stroke', '#D1D5DB')
      .attr('stroke-opacity', 0.7)
      .attr('stroke-width', 1.5)
      .attr('marker-end', 'url(#arrowhead)');

    // Create link labels
    const linkLabel = container
      .append('g')
      .attr('class', 'link-labels')
      .selectAll('text')
      .data(simulationEdges)
      .join('text')
      .attr('class', 'link-label')
      .attr('font-size', '10px')
      .attr('fill', '#6B7280')
      .attr('text-anchor', 'middle')
      .attr('dy', -5)
      .text((d) => d.type.replace(/_/g, ' '));

    // Create node groups
    const node = container
      .append('g')
      .attr('class', 'nodes')
      .selectAll('g')
      .data(simulationNodes)
      .join('g')
      .attr('class', 'node-group')
      .style('cursor', 'pointer');

    // Add circles to nodes
    node
      .append('circle')
      .attr('class', 'node')
      .attr('r', (d) => getNodeRadius(d.id))
      .attr('fill', (d) => getNodeColor(d.type))
      .attr('stroke', (d) => (d.id === centerNodeId ? '#FFF' : 'transparent'))
      .attr('stroke-width', (d) => (d.id === centerNodeId ? 3 : 0))
      .style('filter', (d) =>
        d.id === centerNodeId ? 'drop-shadow(0 0 8px rgba(0,0,0,0.3))' : 'none'
      );

    // Add labels to nodes
    node
      .append('text')
      .attr('class', 'node-label')
      .attr('text-anchor', 'middle')
      .attr('dy', (d) => getNodeRadius(d.id) + 15)
      .attr('font-size', '12px')
      .attr('font-weight', (d) => (d.id === centerNodeId ? '600' : '400'))
      .attr('fill', '#374151')
      .text((d) => d.label);

    // Drag behavior
    function dragstarted(event: d3.D3DragEvent<SVGGElement, SimulationNode, SimulationNode>, d: SimulationNode) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      d.fx = d.x;
      d.fy = d.y;
    }

    function dragged(event: d3.D3DragEvent<SVGGElement, SimulationNode, SimulationNode>, d: SimulationNode) {
      d.fx = event.x;
      d.fy = event.y;
    }

    function dragended(event: d3.D3DragEvent<SVGGElement, SimulationNode, SimulationNode>, d: SimulationNode) {
      if (!event.active) simulation.alphaTarget(0);
      d.fx = null;
      d.fy = null;
    }

    const drag = d3
      .drag<SVGGElement, SimulationNode>()
      .on('start', dragstarted)
      .on('drag', dragged)
      .on('end', dragended);

    // Apply drag to nodes - use type assertion to handle D3 type compatibility
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    node.call(drag as any);

    // Click handler
    node.on('click', (_event, d) => {
      if (onNodeClick) {
        onNodeClick(d);
      }
    });

    // Hover handlers
    node
      .on('mouseenter', (_event, d) => {
        setHoveredNode(d);
        d3.select(_event.currentTarget as SVGGElement)
          .select('circle')
          .transition()
          .duration(150)
          .attr('r', getNodeRadius(d.id) + 4);
      })
      .on('mouseleave', (_event, d) => {
        setHoveredNode(null);
        d3.select(_event.currentTarget as SVGGElement)
          .select('circle')
          .transition()
          .duration(150)
          .attr('r', getNodeRadius(d.id));
      });

    // Update positions on tick
    simulation.on('tick', () => {
      link
        .attr('x1', (d) => (d.source as SimulationNode).x ?? 0)
        .attr('y1', (d) => (d.source as SimulationNode).y ?? 0)
        .attr('x2', (d) => (d.target as SimulationNode).x ?? 0)
        .attr('y2', (d) => (d.target as SimulationNode).y ?? 0);

      linkLabel
        .attr(
          'x',
          (d) =>
            (((d.source as SimulationNode).x ?? 0) + ((d.target as SimulationNode).x ?? 0)) / 2
        )
        .attr(
          'y',
          (d) =>
            (((d.source as SimulationNode).y ?? 0) + ((d.target as SimulationNode).y ?? 0)) / 2
        );

      node.attr('transform', (d) => `translate(${d.x ?? 0},${d.y ?? 0})`);
    });

    // Center the view if there's a center node
    if (centerNodeId) {
      simulation.on('end', () => {
        const centerNode = simulationNodes.find((n) => n.id === centerNodeId);
        if (centerNode && centerNode.x !== undefined && centerNode.y !== undefined) {
          const scale = 1;
          const translateX = svgWidth / 2 - centerNode.x * scale;
          const translateY = svgHeight / 2 - centerNode.y * scale;

          svg
            .transition()
            .duration(500)
            .call(zoom.transform, d3.zoomIdentity.translate(translateX, translateY).scale(scale));
        }
      });
    }

    // Cleanup
    return () => {
      simulation.stop();
    };
  }, [nodes, edges, dimensions, centerNodeId, onNodeClick, getNodeColor, getNodeRadius]);

  // Empty state
  if (nodes.length === 0) {
    return (
      <div
        className={cn(
          'flex items-center justify-center rounded-lg border-2 border-dashed',
          'border-gray-300',
          'bg-gray-50',
          className
        )}
        style={{ width, height }}
      >
        <div className="text-center text-gray-500">
          <svg
            className="mx-auto h-12 w-12 mb-4"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth={1.5}
              d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101m-.758-4.899a4 4 0 005.656 0l4-4a4 4 0 00-5.656-5.656l-1.1 1.1"
            />
          </svg>
          <p>暫無圖譜資料</p>
          <p className="text-sm mt-1">搜尋人物、地點或主題以查看關係圖</p>
        </div>
      </div>
    );
  }

  return (
    <div className={cn('relative', className)} ref={containerRef}>
      {/* Graph SVG */}
      <svg
        ref={svgRef}
        width={dimensions.width}
        height={dimensions.height}
        className="bg-gray-50 rounded-lg"
        style={{ width, height }}
      />

      {/* Tooltip */}
      {hoveredNode && (
        <div
          className={cn(
            'absolute top-4 left-4 z-10',
            'bg-white',
            'border border-gray-200',
            'rounded-lg shadow-lg p-3',
            'max-w-xs'
          )}
        >
          <div className="flex items-center gap-2 mb-1">
            <span
              className="w-3 h-3 rounded-full"
              style={{ backgroundColor: getNodeColor(hoveredNode.type) }}
            />
            <span className="font-medium text-gray-900">
              {hoveredNode.label}
            </span>
          </div>
          <p className="text-sm text-gray-500">
            {hoveredNode.type === 'PERSON' ? '人物' : null}
            {hoveredNode.type === 'PLACE' ? '地點' : null}
            {hoveredNode.type === 'GROUP' ? '群體' : null}
            {hoveredNode.type === 'EVENT' ? '事件' : null}
            {hoveredNode.type === 'TOPIC' ? '主題' : null}
          </p>
          {typeof hoveredNode.properties?.description === 'string' && hoveredNode.properties.description && (
            <p className="text-xs text-gray-400 mt-1">
              {hoveredNode.properties.description}
            </p>
          )}
        </div>
      )}

      {/* Legend */}
      <div
        className={cn(
          'absolute bottom-4 left-4 z-10',
          'bg-white/90',
          'backdrop-blur-sm',
          'border border-gray-200',
          'rounded-lg shadow-sm p-3'
        )}
      >
        <p className="text-xs font-medium text-gray-700 mb-2">圖例</p>
        <div className="flex flex-wrap gap-3">
          {LEGEND_ITEMS.map((item) => (
            <div key={item.type} className="flex items-center gap-1.5">
              <span
                className="w-3 h-3 rounded-full"
                style={{ backgroundColor: item.color }}
              />
              <span className="text-xs text-gray-600">{item.label}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Controls hint */}
      <div
        className={cn(
          'absolute bottom-4 right-4 z-10',
          'bg-white/90',
          'backdrop-blur-sm',
          'border border-gray-200',
          'rounded-lg shadow-sm px-3 py-2'
        )}
      >
        <p className="text-xs text-gray-500">
          滑鼠拖曳移動節點 | 滾輪縮放 | 點擊查看詳情
        </p>
      </div>
    </div>
  );
}

export default GraphViewer;
