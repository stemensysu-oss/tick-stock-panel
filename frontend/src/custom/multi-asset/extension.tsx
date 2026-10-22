import { PanelsTopLeft } from 'lucide-react'
import type { FrontendExtension } from '@/extensions/types'
import { MultiAssetPage } from './MultiAssetPage'

const extension: FrontendExtension = {
  id: 'stemensysu.multi-asset',
  apiVersion: 1,
  routes: [{ id: 'multi-asset-workspace', path: '/multi-asset', component: MultiAssetPage }],
  navigation: [{ id: 'multi-asset-workspace', routeId: 'multi-asset-workspace', label: '多资产工作台', icon: PanelsTopLeft, order: 505 }],
}
export default extension
