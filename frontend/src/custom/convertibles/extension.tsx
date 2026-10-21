import { ArrowLeftRight } from 'lucide-react'
import type { FrontendExtension } from '@/extensions/types'
import { ConvertiblesPage } from './ConvertiblesPage'

const extension: FrontendExtension = {
  id: 'stemensysu.convertibles',
  apiVersion: 1,
  routes: [{ id: 'convertibles-research', path: '/convertibles', component: ConvertiblesPage }],
  navigation: [{ id: 'convertibles-research', routeId: 'convertibles-research', label: '可转债工作台', icon: ArrowLeftRight, order: 520 }],
}

export default extension
