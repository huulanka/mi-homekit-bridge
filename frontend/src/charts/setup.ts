import { HeatmapChart, LineChart } from 'echarts/charts'
import type { HeatmapSeriesOption, LineSeriesOption } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkLineComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import type {
  DataZoomComponentOption,
  GridComponentOption,
  LegendComponentOption,
  MarkLineComponentOption,
  TooltipComponentOption,
  VisualMapComponentOption,
} from 'echarts/components'
import * as echarts from 'echarts/core'
import type { ComposeOption } from 'echarts/core'
import { LabelLayout } from 'echarts/features'
import { SVGRenderer } from 'echarts/renderers'

// Only what the dashboard uses, to keep the bundle small.
echarts.use([
  LineChart,
  HeatmapChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
  MarkLineComponent,
  DataZoomComponent,
  LabelLayout,
  SVGRenderer,
])

export type ChartOption = ComposeOption<
  | LineSeriesOption
  | HeatmapSeriesOption
  | GridComponentOption
  | LegendComponentOption
  | TooltipComponentOption
  | VisualMapComponentOption
  | MarkLineComponentOption
  | DataZoomComponentOption
>

export { echarts }
