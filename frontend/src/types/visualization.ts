/**
 * Type definitions for data visualization.
 */

import type { ChartType, ChartConfig } from './message';

export interface PlotlyData {
  x: (string | number)[];
  y: (string | number)[];
  type: string;
  mode?: string;
  name?: string;
  marker?: {
    color?: string | string[];
    size?: number | number[];
  };
  text?: string[];
  hoverinfo?: string;
}

export interface PlotlyLayout {
  title?: string | { text: string };
  xaxis?: {
    title?: string;
    tickangle?: number;
  };
  yaxis?: {
    title?: string;
  };
  barmode?: 'group' | 'stack' | 'overlay' | 'relative';
  showlegend?: boolean;
  margin?: {
    l?: number;
    r?: number;
    t?: number;
    b?: number;
  };
  autosize?: boolean;
  height?: number;
  width?: number;
}

export interface PlotlyConfig {
  responsive?: boolean;
  displayModeBar?: boolean;
  displaylogo?: boolean;
  modeBarButtonsToRemove?: string[];
}

export function chartConfigToPlotly(config: ChartConfig): {
  data: PlotlyData[];
  layout: PlotlyLayout;
} {
  const { chart_type, title, x_axis, y_axis, data, x_label, y_label } = config;

  // Extract x and y values
  const xValues = data.map(row => row[x_axis] as string | number);
  const yValues = data.map(row => row[y_axis] as string | number);

  let plotlyType: string;
  let mode: string | undefined;

  switch (chart_type) {
    case 'bar':
      plotlyType = 'bar';
      break;
    case 'line':
      plotlyType = 'scatter';
      mode = 'lines+markers';
      break;
    case 'scatter':
      plotlyType = 'scatter';
      mode = 'markers';
      break;
    case 'pie':
      plotlyType = 'pie';
      break;
    case 'histogram':
      plotlyType = 'histogram';
      break;
    case 'heatmap':
      plotlyType = 'heatmap';
      break;
    default:
      plotlyType = 'bar';
  }

  const plotlyData: PlotlyData[] = [{
    x: xValues,
    y: yValues,
    type: plotlyType,
    mode,
    marker: {
      color: '#3B82F6' // Anthology blue
    }
  }];

  const layout: PlotlyLayout = {
    title: { text: title },
    xaxis: {
      title: x_label || x_axis,
      tickangle: -45
    },
    yaxis: {
      title: y_label || y_axis
    },
    margin: {
      l: 60,
      r: 30,
      t: 50,
      b: 100
    },
    autosize: true
  };

  return { data: plotlyData, layout };
}

export interface ExportOptions {
  format: 'csv' | 'excel' | 'pdf';
  filename?: string;
}

export interface TableColumn {
  key: string;
  label: string;
  sortable?: boolean;
  width?: string | number;
  align?: 'left' | 'center' | 'right';
  format?: (value: unknown) => string;
}
