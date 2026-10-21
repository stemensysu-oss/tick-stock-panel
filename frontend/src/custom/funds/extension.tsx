import { ChartNoAxesCombined } from 'lucide-react'
import type { FrontendExtension } from '@/extensions/types'
import { FundsPage } from './FundsPage'

const extension: FrontendExtension = {
  id: 'stemensysu.funds',
  apiVersion: 1,
  routes: [{ id: 'funds-research', path: '/funds', component: FundsPage }],
  navigation: [{ id: 'funds-research', routeId: 'funds-research', label: '基金研究', icon: ChartNoAxesCombined, order: 510 }],
}

export default extension
