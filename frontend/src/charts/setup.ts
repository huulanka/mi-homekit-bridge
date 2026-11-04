import { BarChart, HeatmapChart, LineChart } from 'echarts/charts'
import type { BarSeriesOption, HeatmapSeriesOption, LineSeriesOption } from 'echarts/charts'
import {
  CalendarComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
  VisualMapComponent,
} from 'echarts/components'
import type {
  CalendarComponentOption,
  DataZoomComponentOption,
  GridComponentOption,
  LegendComponentOption,
  MarkAreaComponentOption,
  MarkLineComponentOption,
  MarkPointComponentOption,
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
  BarChart,
  HeatmapChart,
  GridComponent,
  LegendComponent,
  TooltipComponent,
  VisualMapComponent,
  CalendarComponent,
  MarkLineComponent,
  MarkAreaComponent,
  MarkPointComponent,
  DataZoomComponent,
  LabelLayout,
  SVGRenderer,
])

export type ChartOption = ComposeOption<
  | LineSeriesOption
  | BarSeriesOption
  | HeatmapSeriesOption
  | GridComponentOption
  | LegendComponentOption
  | TooltipComponentOption
  | VisualMapComponentOption
  | CalendarComponentOption
  | MarkLineComponentOption
  | MarkAreaComponentOption
  | MarkPointComponentOption
  | DataZoomComponentOption
>

export { echarts }
