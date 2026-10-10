import { useEffect, useMemo, useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { RefreshCw } from 'lucide-react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import {
  api, type Donor, type Facility, type FacilityStock, type MatchResponse,
  type NearbyDonor, type SosEvent, type SosReward, type DensityCell, type TransferOffer, type AcceptedDonorCell,
} from '../lib/api'
import { useAuth } from '../lib/auth'
import { COMPONENT_LABELS, URGENCY_LABELS } from '../lib/constants'

/**
 * Bản đồ điều phối — ba lớp trên cùng một khung nhìn.
 *
 *   1. Bệnh viện  — chấm to nhỏ theo tồn kho của nhóm máu đang lọc
 *   2. Nhu cầu    — ca SOS đang mở, đỏ và nhấp nháy nếu cấp cứu
 *   3. Người hiến — ô lưới H3 tô đậm theo mật độ
 *
 * Lớp 3 KHÔNG BAO GIỜ là chấm cá nhân. Hệ thống chỉ lưu ô lưới ~1,2 km chứ
 * không lưu toạ độ, và máy chủ còn ẩn hẳn ô nào có dưới `min_donors` người
 * (k-ẩn danh). Chấm từng người lên bản đồ sẽ phá đúng cam kết riêng tư mà cả
 * hệ thống dựa vào — nên đây là giới hạn cố ý, không phải thiếu sót.
 */

const ABO_OPTIONS = ['O', 'A', 'B', 'AB']
const HCMC_CENTER: [number, number] = [10.776, 106.68]
const DONOR_MARKER_PANE = 'donor-markers'
const SOS_RING_START_MINUTES = [0, 10, 25, 45]
const SOS_FINAL_RING_TIMEOUT_MS = 10 * 60_000

function secondsUntilNextRing(event: SosEvent, now: number): number | null {
  const nextRingStart = SOS_RING_START_MINUTES[event.ring + 1]
  const openedAt = Date.parse(event.opened_at)
  if (nextRingStart == null || !Number.isFinite(openedAt)) return null
  return Math.max(0, Math.ceil((openedAt + nextRingStart * 60_000 - now) / 1000))
}

function secondsUntilFinalTimeout(
  event: SosEvent,
  notifications: { ring: number; created_at: string }[],
  now: number,
): number | null {
  if (event.ring < 3) return null
  const finalInvitations = notifications.filter(notification => notification.ring === 3)
  const latestFinalInvitation = finalInvitations.reduce(
    (latest, notification) => Math.max(latest, Date.parse(notification.created_at)),
    Date.parse(event.opened_at),
  )
  if (!Number.isFinite(latestFinalInvitation)) return null
  return Math.max(0, Math.ceil((latestFinalInvitation + SOS_FINAL_RING_TIMEOUT_MS - now) / 1000))
}

function formatCountdown(seconds: number): string {
  const minutes = Math.floor(seconds / 60)
  const remainder = seconds % 60
  return `${String(minutes).padStart(2, '0')}:${String(remainder).padStart(2, '0')}`
}

function metricFreshness(updatedAt: number, isFetching: boolean): string {
  if (isFetching) return 'Đang cập nhật…'
  if (!updatedAt) return 'Chưa có dữ liệu'
  return `Cập nhật lúc ${new Date(updatedAt).toLocaleTimeString('vi-VN')}`
}

/** Màu theo mức tồn: đỏ = cạn, xanh = dồi dào. */
function stockColor(count: number): string {
  if (count === 0) return '#991b1b'
  if (count < 20) return '#dc2626'
  if (count < 60) return '#f59e0b'
  if (count < 150) return '#65a30d'
  return '#15803d'
}

function stockLabel(count: number): string {
  if (count === 0) return 'Hết'
  if (count < 20) return 'Rất thấp'
  if (count < 60) return 'Thấp'
  if (count < 150) return 'Đủ'
  return 'Dồi dào'
}

const SOS_RING_MINUTES = 45
const DELIVERY_BUFFER_MINUTES = 15

/** Keep hospital response time inside the clinical window left after ETA + SOS. */
function calculateYellowWaitMinutes(
  urgency: string,
  neededBy: string,
  fastestEtaSeconds: number | null,
  hasCompatibleCandidates: boolean,
): number {
  if (!hasCompatibleCandidates) return 0
  const urgencyCap = urgency === 'emergency' ? 5 : urgency === 'urgent' ? 10 : 20
  const etaMinutes = fastestEtaSeconds == null ? 30 : fastestEtaSeconds / 60
  const minutesUntilNeeded = (Date.parse(neededBy) - Date.now()) / 60000
  const remainingWindow = Math.floor(
    minutesUntilNeeded - etaMinutes - SOS_RING_MINUTES - DELIVERY_BUFFER_MINUTES,
  )
  return Math.max(0, Math.min(urgencyCap, remainingWindow))
}

/** Tạo một vị trí đại diện ổn định trong ô H3; không phải vị trí GPS cá nhân. */
function representativeDonorPoint(cell: DensityCell, donorId: string): [number, number] {
  const center: [number, number] = [cell.lat, cell.lon]
  const vertices = cell.boundary
  if (vertices.length < 3) return center

  const triangles = vertices.map((a, index) => {
    const b = vertices[(index + 1) % vertices.length]
    const area = Math.abs((a[1] - center[1]) * (b[0] - center[0]) - (b[1] - center[1]) * (a[0] - center[0]))
    return { a, b, area }
  })
  const totalArea = triangles.reduce((sum, triangle) => sum + triangle.area, 0)
  if (!totalArea) return center

  let seed = [...donorId].reduce((value, char) => (Math.imul(value, 31) + char.charCodeAt(0)) | 0, 7) >>> 0
  const random = () => {
    seed = (seed + 0x6D2B79F5) | 0
    let value = seed
    value = Math.imul(value ^ (value >>> 15), value | 1)
    value ^= value + Math.imul(value ^ (value >>> 7), value | 61)
    return ((value ^ (value >>> 14)) >>> 0) / 4294967296
  }

  let target = random() * totalArea
  const triangle = triangles.find(item => (target -= item.area) <= 0) ?? triangles[triangles.length - 1]
  const root = Math.sqrt(random())
  const along = random()
  return [
    center[0] * (1 - root) + triangle.a[0] * root * (1 - along) + triangle.b[0] * root * along,
    center[1] * (1 - root) + triangle.a[1] * root * (1 - along) + triangle.b[1] * root * along,
  ]
}

export default function MapView() {
  const queryClient = useQueryClient()
  const { session } = useAuth()
  const [abo, setAbo] = useState('O')
  const [rh, setRh] = useState('+')
  const [component, setComponent] = useState('RBC')
  const [showStock, setShowStock] = useState(true)
  const [showDonors, setShowDonors] = useState(true)
  const [showSos, setShowSos] = useState(true)
  const [mapReady, setMapReady] = useState(false)
  const [expandedDonorCell, setExpandedDonorCell] = useState<string | null>(null)
  const [selectedDonorId, setSelectedDonorId] = useState<string | null>(null)
  const [sourceId, setSourceId] = useState('')
  const [destinationId, setDestinationId] = useState('')
  const [routeRequestVersion, setRouteRequestVersion] = useState(0)
  const [workflow, setWorkflow] = useState<'dispatch' | 'sos' | null>(null)
  const [matchQty, setMatchQty] = useState(1)
  const [matchUrgency, setMatchUrgency] = useState('urgent')
  const [recipientSex, setRecipientSex] = useState('')
  const [recipientAge, setRecipientAge] = useState('')
  const [neededBy, setNeededBy] = useState(() => {
    const date = new Date(Date.now() + 6 * 60 * 60 * 1000)
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
  })
  const [matchResult, setMatchResult] = useState<MatchResponse | null>(null)
  const [dispatchRun, setDispatchRun] = useState<{
    requestId: string
    destinationFacilityId: string
    qty: number
    waitMinutes: number
    fastestEtaSeconds: number | null
    expiresAt: string
  } | null>(null)
  const [clockNow, setClockNow] = useState(Date.now())
  const [sosQty, setSosQty] = useState(1)
  const [sosUrgency, setSosUrgency] = useState('emergency')
  const [openedSos, setOpenedSos] = useState<SosEvent | null>(null)
  const [sosTrackingEnabled, setSosTrackingEnabled] = useState(() => {
    try {
      return typeof window === 'undefined' || window.localStorage.getItem('bb_map_sos_tracking') !== 'disabled'
    } catch {
      return true
    }
  })

  // Chủ đề đang hiển thị thật sự (đã giải quyết xong "theo hệ thống").
  const [dark, setDark] = useState(false)
  useEffect(() => {
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const resolve = () => {
      const choice = document.documentElement.getAttribute('data-theme')
      setDark(choice === 'dark' || (choice !== 'light' && mq.matches))
    }
    resolve()
    mq.addEventListener('change', resolve)
    // Nút chuyển chủ đề đổi thuộc tính trên <html>, theo dõi để nền đổi theo.
    const obs = new MutationObserver(resolve)
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
    return () => { mq.removeEventListener('change', resolve); obs.disconnect() }
  }, [])

  const boxRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.LayerGroup | null>(null)
  const routeLayerRef = useRef<L.LayerGroup | null>(null)
  const focusedResponderCells = useRef('')

  const facilitiesQuery = useQuery({
    queryKey: ['facilities'],
    queryFn: () => api.listFacilities(),
  })
  const facilities = facilitiesQuery.data

  const stockQuery = useQuery({
    queryKey: ['stock-by-facility', component],
    queryFn: () => api.inventoryByFacility(component),
    refetchInterval: 30000,
    refetchIntervalInBackground: true,
  })
  const stock = stockQuery.data

  const eventsQuery = useQuery({
    queryKey: ['sos-events-map'],
    queryFn: () => api.listSosEvents(),
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  })
  const events = eventsQuery.data
  const openEventsQuery = useQuery({
    queryKey: ['sos-open-events-map'],
    queryFn: api.listOpenSosEvents,
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  })
  const activeSosEvents = useMemo(
    () => openEventsQuery.isError
      ? eventsQuery.isError ? [] : (events ?? []).filter(event => event.status === 'open')
      : openEventsQuery.data ?? (events ?? []).filter(event => event.status === 'open'),
    [openEventsQuery.data, openEventsQuery.isError, events, eventsQuery.isError],
  )
  const trackableSosEvents = useMemo(
    () => eventsQuery.isError
      ? []
      : (events ?? []).filter(event => ['open', 'fulfilled', 'expired'].includes(event.status)),
    [events, eventsQuery.isError],
  )
  const openedSosQuery = useQuery({
    queryKey: ['map-sos-event-detail', openedSos?.id],
    queryFn: () => api.getSosEvent(openedSos!.id),
    enabled: !!openedSos?.id,
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  })
  const displayedOpenedSos = openedSosQuery.data ?? openedSos
  const trackedSosEvent = useMemo(
    () => sosTrackingEnabled
      ? activeSosEvents.find(event => event.request_id === dispatchRun?.requestId)
        ?? trackableSosEvents.find(event => event.request_id === dispatchRun?.requestId)
        ?? activeSosEvents.find(event => !!event.request_id)
        ?? activeSosEvents[0]
        ?? trackableSosEvents.find(event => !!event.request_id)
        ?? trackableSosEvents[0]
      : undefined,
    [activeSosEvents, trackableSosEvents, dispatchRun?.requestId, sosTrackingEnabled],
  )
  const canManageTrackedSos = session?.role === 'admin'
    || (!!trackedSosEvent?.facility_id && session?.facilityId === trackedSosEvent.facility_id)
  const trackedSosRespondersQuery = useQuery({
    queryKey: ['sos-responders', trackedSosEvent?.id],
    queryFn: () => api.listSosResponders(trackedSosEvent!.id),
    enabled: !!trackedSosEvent && canManageTrackedSos,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
  })
  const trackedSosRewardsQuery = useQuery({
    queryKey: ['sos-rewards', trackedSosEvent?.id],
    queryFn: () => api.listSosRewards(trackedSosEvent!.id),
    enabled: !!trackedSosEvent && canManageTrackedSos,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
  })
  const trackedRewardByDonor = new Map<string, SosReward['status']>(
    (trackedSosRewardsQuery.data ?? []).map(
      (reward): [string, SosReward['status']] => [reward.donor_id, reward.status],
    ),
  )
  const trackedPendingFollowups = (trackedSosRespondersQuery.data ?? []).filter(responder =>
    !['compensation_proposed', 'mock_ready', 'not_completed'].includes(
      trackedRewardByDonor.get(responder.donor_id) ?? '',
    ),
  ).length
  const canCompleteTrackedSos = !!trackedSosEvent
    && ['fulfilled', 'expired'].includes(trackedSosEvent.status)
    && trackedSosRespondersQuery.data !== undefined
    && trackedSosRewardsQuery.data !== undefined
    && trackedPendingFollowups === 0
  const trackedSosNotificationsQuery = useQuery({
    queryKey: ['map-sos-notifications', trackedSosEvent?.id],
    queryFn: () => api.listSosNotifications(trackedSosEvent!.id),
    enabled: !!trackedSosEvent && canManageTrackedSos && trackedSosEvent.ring >= 3,
    refetchInterval: 3000,
    refetchIntervalInBackground: true,
  })

  const stopSosTracking = () => {
    setSosTrackingEnabled(false)
    try { window.localStorage.setItem('bb_map_sos_tracking', 'disabled') } catch { /* Keep the current choice for this page. */ }
  }
  const resumeSosTracking = () => {
    setSosTrackingEnabled(true)
    try { window.localStorage.removeItem('bb_map_sos_tracking') } catch { /* Keep the current choice for this page. */ }
  }

  const densityQuery = useQuery({
    queryKey: ['donor-density', abo, rh],
    // Để nguyên ngưỡng k-ẩn danh mặc định của máy chủ (3). Hạ xuống 1 thì bản
    // đồ trông "đầy" hơn nhưng một ô chỉ có đúng một người là đủ để lần ra
    // người đó — chính thứ cả hệ thống cam kết không làm.
    queryFn: () => api.donorDensity({ abo, rh }),
    refetchInterval: 60000,
    refetchIntervalInBackground: true,
  })

  const refreshMapStats = async () => {
    await Promise.all([stockQuery.refetch(), openEventsQuery.refetch(), densityQuery.refetch()])
  }
  const statsRefreshing = stockQuery.isFetching || openEventsQuery.isFetching || densityQuery.isFetching

  const acceptedDonorCellsQuery = useQuery({
    queryKey: ['sos-accepted-donor-cells'],
    queryFn: () => api.listAcceptedDonorCells(),
    enabled: showDonors,
    refetchInterval: 15000,
    refetchIntervalInBackground: true,
  })

  const sharedResponderLocationsQuery = useQuery({
    queryKey: ['sos-shared-locations', trackedSosEvent?.id],
    queryFn: () => api.listSosResponderLocations(trackedSosEvent!.id),
    enabled: showDonors && !!trackedSosEvent,
    refetchInterval: 10000,
    refetchIntervalInBackground: true,
  })

  useEffect(() => {
    if (!dispatchRun && activeSosEvents.length === 0) return
    const timer = window.setInterval(() => setClockNow(Date.now()), 1000)
    return () => window.clearInterval(timer)
  }, [dispatchRun, activeSosEvents.length])

  useEffect(() => {
    if (!destinationId && facilities?.length) {
      setDestinationId(
        facilities.find(f => f.id === session?.facilityId)?.id ?? facilities[0].id,
      )
    }
  }, [destinationId, facilities, session?.facilityId])

  const destinationFacility = facilities?.find(f => f.id === destinationId)
  const routeDestinationFacility = facilities?.find(f => f.id === dispatchRun?.destinationFacilityId) ?? destinationFacility
  const trackedFacility = facilities?.find(f => f.id === trackedSosEvent?.facility_id)
  const sourceFacility = facilities?.find(f => f.id === sourceId)
  const { data: routeEta, isLoading: routeLoading, error: routeError } = useQuery({
    queryKey: ['map-route', sourceId, routeDestinationFacility?.id, routeRequestVersion],
    queryFn: () => {
      if (!sourceFacility || !routeDestinationFacility) throw new Error('Chưa có tuyến điều chuyển để tính.')
      return api.getEta(sourceFacility.lat, sourceFacility.lon, routeDestinationFacility.lat, routeDestinationFacility.lon)
    },
    enabled: !!sourceFacility && !!routeDestinationFacility && sourceId !== routeDestinationFacility.id,
    refetchInterval: 60000,
    refetchIntervalInBackground: true,
  })
  const sharedLocation = sharedResponderLocationsQuery.data?.[0]
  const { data: pickupRoute } = useQuery({
    queryKey: ['map-sos-pickup-route', trackedSosEvent?.id, sharedLocation?.latitude, sharedLocation?.longitude, trackedFacility?.id],
    queryFn: () => api.getEta(
      sharedLocation!.latitude,
      sharedLocation!.longitude,
      trackedFacility!.lat,
      trackedFacility!.lon,
    ),
    enabled: showDonors && !!sharedLocation && !!trackedFacility,
  })
  useEffect(() => {
    const map = mapRef.current
    const routeLayer = routeLayerRef.current
    if (!map || !routeLayer || !mapReady) return
    routeLayer.clearLayers()
    if (!routeEta?.geometry || routeEta.geometry.length < 2
      || !['road', 'straight_line'].includes(routeEta.routing_mode)) return

    const routePoints = routeEta.geometry.filter(([lat, lon]) => Number.isFinite(lat) && Number.isFinite(lon))
    if (routePoints.length < 2) return
    const isRoadRoute = routeEta.routing_mode === 'road'
    const routeLabel = isRoadRoute ? 'Tuyến hỗ trợ liên viện' : 'Tuyến tham khảo đường thẳng'
    const line = L.polyline(routePoints, {
      color: isRoadRoute ? '#2563eb' : '#d97706',
      weight: 5,
      opacity: 0.95,
      dashArray: isRoadRoute ? undefined : '10 8',
    })
      .bindPopup(`<b>${routeLabel}</b><br>${routeEta.duration_min.toFixed(1)} phút · ${(routeEta.distance_m / 1000).toFixed(1)} km · ${routeEta.provider}`)
      .addTo(routeLayer)
      .bringToFront()
    const bounds = line.getBounds()
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [42, 42], maxZoom: 15 })
  }, [routeEta, mapReady, sourceFacility?.id, routeDestinationFacility?.id])
  useEffect(() => {
    const cells = acceptedDonorCellsQuery.data ?? []
    if (!mapReady || sourceId || cells.length === 0 || !mapRef.current) return
    const key = cells.map(cell => cell.h3_cell).sort().join('|')
    if (key === focusedResponderCells.current) return
    focusedResponderCells.current = key
    mapRef.current.fitBounds(
      L.latLngBounds(cells.map(cell => [cell.lat, cell.lon] as [number, number])),
      { padding: [42, 42], maxZoom: 12 },
    )
  }, [acceptedDonorCellsQuery.data, mapReady, sourceId])
  const density = densityQuery.isError ? undefined : densityQuery.data

  const matchSearch = useMutation({
    mutationFn: async () => {
      if (!destinationFacility) throw new Error('Chọn cơ sở cần máu trước khi phát yêu cầu.')
      if (!Number.isFinite(Date.parse(neededBy))) throw new Error('Chọn thời điểm cần máu hợp lệ.')
      const request = await api.createTransferRequest({
        requester_facility_id: destinationFacility.id,
        component_code: component,
        abo,
        rh: rh || undefined,
        qty: matchQty,
        urgency: matchUrgency,
        needed_by: new Date(neededBy).toISOString(),
        recipient_sex: recipientSex || undefined,
        recipient_age: recipientAge ? Number(recipientAge) : undefined,
      })
      const result = await api.findMatches(request.id)
      const compatible = result.results.filter(item => item.compatible)
      const fastestEtaSeconds = compatible.reduce<number | null>((fastest, item) => {
        if (item.eta_seconds == null) return fastest
        return fastest == null ? item.eta_seconds : Math.min(fastest, item.eta_seconds)
      }, null)
      const waitMinutes = calculateYellowWaitMinutes(
        matchUrgency, new Date(neededBy).toISOString(), fastestEtaSeconds, compatible.length > 0,
      )
      const offers = await api.broadcastTransferRequest(request.id, waitMinutes)
      return { request, result, offers, waitMinutes, fastestEtaSeconds }
    },
    onSuccess: async ({ request, result, offers, waitMinutes, fastestEtaSeconds }) => {
      setMatchResult(result)
      setDispatchRun({
        requestId: request.id,
        destinationFacilityId: request.requester_facility_id,
        qty: matchQty,
        waitMinutes,
        fastestEtaSeconds,
        expiresAt: offers[0]?.expires_at ?? new Date(Date.now() + waitMinutes * 60000).toISOString(),
      })
      setSourceId('')
      await queryClient.invalidateQueries({ queryKey: ['stock-by-facility'] })
      await queryClient.invalidateQueries({ queryKey: ['sos-events-map'] })
      await queryClient.invalidateQueries({ queryKey: ['sos-open-events-map'] })
    },
  })

  const { data: transferOffers } = useQuery({
    queryKey: ['map-transfer-offers', dispatchRun?.requestId],
    queryFn: () => api.listTransferOffers(dispatchRun!.requestId),
    enabled: !!dispatchRun,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
  })

  const { data: incomingOffers, error: incomingOffersError } = useQuery({
    queryKey: ['map-incoming-transfer-offers', session?.facilityId, session?.role],
    queryFn: () => api.listIncomingTransferOffers(session?.facilityId ?? undefined),
    enabled: !!session?.facilityId,
    refetchInterval: 5000,
    refetchIntervalInBackground: true,
  })

  const respondToOffer = useMutation({
    mutationFn: ({ offerId, accept, sourceFacilityId }: { offerId: string; accept: boolean; sourceFacilityId: string }) =>
      api.respondToTransferOffer(offerId, accept, session?.facilityId ?? sourceFacilityId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['map-incoming-transfer-offers'] })
      if (dispatchRun) await queryClient.invalidateQueries({ queryKey: ['map-transfer-offers', dispatchRun.requestId] })
      await queryClient.invalidateQueries({ queryKey: ['stock-by-facility'] })
      await queryClient.invalidateQueries({ queryKey: ['sos-events-map'] })
      await queryClient.invalidateQueries({ queryKey: ['sos-open-events-map'] })
    },
  })

  // The map needs actual mock donor IDs (not just synthetic count dots) so a
  // clicked person can open the existing staff-only donor profile endpoint.
  const mapDonorSearch = useQuery({
    queryKey: ['map-donor-profiles', destinationFacility?.h3_cell, abo, rh, component],
    queryFn: () => api.findNearbyDonors({
      h3Cell: destinationFacility!.h3_cell!, abo, rh, componentCode: component,
      ring: 3, verifiedOnly: true, eligibleOnly: false, limit: 500,
    }),
    enabled: showDonors && !!destinationFacility?.h3_cell,
  })

  const selectedDonorProfile = useQuery({
    queryKey: ['map-donor-profile', selectedDonorId, component],
    queryFn: () => api.getDonor(selectedDonorId!, component),
    enabled: !!selectedDonorId,
  })

  const openSos = useMutation({
    mutationFn: (options: { requestId?: string; qty?: number; urgency?: string }) => {
      if (!destinationFacility) throw new Error('Chọn cơ sở phát SOS trên bản đồ trước.')
      return api.createSosEvent({
        facility_id: destinationFacility.id,
        component_code: component,
        abo, rh: rh || undefined,
        urgency: options.urgency ?? sosUrgency,
        qty: options.qty ?? sosQty,
        ring: 0,
        request_id: options.requestId,
        h3_cell: destinationFacility.h3_cell ?? undefined,
      })
    },
    onSuccess: async event => {
      setOpenedSos(event)
      await queryClient.invalidateQueries({ queryKey: ['open-sos'] })
      await queryClient.invalidateQueries({ queryKey: ['sos-open-events'] })
      await queryClient.invalidateQueries({ queryKey: ['sos-events-map'] })
      await queryClient.invalidateQueries({ queryKey: ['sos-open-events-map'] })
    },
  })

  const advanceSos = useMutation({
    mutationFn: (eventId: string) => api.escalateSosEvent(eventId),
    onSuccess: async event => {
      setOpenedSos(event)
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['open-sos'] }),
        queryClient.invalidateQueries({ queryKey: ['sos-open-events'] }),
        queryClient.invalidateQueries({ queryKey: ['sos-events-map'] }),
        queryClient.invalidateQueries({ queryKey: ['sos-open-events-map'] }),
      ])
    },
  })

  const completeSos = useMutation({
    mutationFn: (eventId: string) => api.completeSosEvent(eventId),
    onSuccess: async (_event, eventId) => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ['sos-events-map'] }),
        queryClient.invalidateQueries({ queryKey: ['sos-open-events-map'] }),
        queryClient.invalidateQueries({ queryKey: ['sos-event-history'] }),
        queryClient.invalidateQueries({ queryKey: ['map-sos-event-detail', eventId] }),
      ])
    },
  })

  const linkedSosFromList = events?.find(event => event.request_id === dispatchRun?.requestId)
    ?? activeSosEvents.find(event => event.request_id === dispatchRun?.requestId)
  const linkedSos = openedSosQuery.data?.request_id === dispatchRun?.requestId
    ? openedSosQuery.data
    : linkedSosFromList
  const acceptedQty = (transferOffers ?? [])
    .reduce((sum, offer) => sum + (offer.accepted_qty ?? 0), 0)
  const pendingOfferCount = (transferOffers ?? []).filter(offer => offer.status === 'pending').length
  const allOffersFinished = transferOffers !== undefined && pendingOfferCount === 0
  const dispatchPhase = linkedSos
    ? 'sos'
    : dispatchRun && acceptedQty >= dispatchRun.qty
      ? 'fulfilled'
      : dispatchRun && (allOffersFinished || clockNow >= Date.parse(dispatchRun.expiresAt))
        ? 'sos_pending'
        : 'waiting'
  const yellowSecondsLeft = dispatchRun
    ? Math.max(0, Math.ceil((Date.parse(dispatchRun.expiresAt) - clockNow) / 1000))
    : 0

  useEffect(() => {
    if (linkedSos) setOpenedSos(linkedSos)
  }, [linkedSos?.id, linkedSos?.status, linkedSos?.ring, linkedSos?.accept_count, linkedSos?.donors_notified])

  const bloodType = rh ? `${abo}${rh}` : `${abo} (RhD chưa rõ)`

  /** Tồn kho của nhóm máu đang chọn, gom theo cơ sở. */
  const stockByFacility = useMemo(() => {
    const m = new Map<string, number>()
    if (stockQuery.isError) return m
    for (const r of (stock ?? []) as FacilityStock[]) {
      if (r.abo !== abo || (rh && r.rh !== rh)) continue
      m.set(r.facility_id, (m.get(r.facility_id) ?? 0) + r.count)
    }
    return m
  }, [stock, stockQuery.isError, abo, rh])

  // ── Dựng bản đồ một lần ────────────────────────────────────────
  useEffect(() => {
    if (mapRef.current || !boxRef.current) return
    const map = L.map(boxRef.current, { zoomControl: true }).setView(HCMC_CENTER, 12)
    const donorPane = map.createPane(DONOR_MARKER_PANE)
    donorPane.style.zIndex = '640'
    donorPane.style.pointerEvents = 'auto'
    mapRef.current = map
    layerRef.current = L.layerGroup().addTo(map)
    routeLayerRef.current = L.layerGroup().addTo(map)
    setMapReady(true)

    // Leaflet đo khung ngay lúc dựng; nếu thẻ cha còn đang bố trí thì bản đồ
    // ra kích thước 0 và chỉ hiện một mảng xám.
    setTimeout(() => map.invalidateSize(), 0)

    return () => { map.remove(); mapRef.current = null; layerRef.current = null; routeLayerRef.current = null }
  }, [])

  // ── Nền bản đồ ─────────────────────────────────────────────────
  //
  // Hai nguồn đã thử và LOẠI, ghi lại để đừng ai quay lại:
  //   · tile.openstreetmap.org — chính sách OSM chặn ứng dụng không định danh,
  //     trình duyệt nhận 503 hàng loạt và bản đồ ra một mảng xám.
  //   · basemaps.cartocdn.com — nay đòi API key, in đè chữ "API KEY REQUIRED"
  //     lên khắp nền.
  // Máy chủ của cộng đồng OSM Đức phục vụ được, không cần khoá, cùng dữ liệu OSM.
  useEffect(() => {
    const map = mapRef.current
    if (!map) return
    const tiles = L.tileLayer('https://tile.openstreetmap.de/{z}/{x}/{y}.png', {
      attribution: '© OpenStreetMap contributors',
      maxZoom: 18,
    }).addTo(map)
    return () => { tiles.remove() }
  }, [])

  // ── Vẽ lại ba lớp mỗi khi dữ liệu đổi ──────────────────────────
  useEffect(() => {
    const layer = layerRef.current
    if (!layer || !facilities) return
    layer.clearLayers()
    const facById = new Map((facilities as Facility[]).map(f => [f.id, f]))

    // Donors have mock profile IDs, but only an H3 cell is stored for location.
    // Place clickable representative dots inside that cell, never on real GPS.
    if (showDonors) {
      for (const cell of (density?.cells ?? []) as DensityCell[]) {
        if (expandedDonorCell === cell.h3_cell) {
          L.polygon(cell.boundary, {
            color: '#7c3aed', weight: 1, fillColor: '#7c3aed', fillOpacity: 0.05,
          }).on('click', () => setExpandedDonorCell(null)).addTo(layer)

          const donorsInCell = ((mapDonorSearch.data?.donors ?? []) as NearbyDonor[])
            .filter(donor => donor.h3_cell === cell.h3_cell)
            .sort((a, b) => a.donor_id.localeCompare(b.donor_id))
          donorsInCell.forEach((donor, index) => {
            const point = representativeDonorPoint(cell, donor.donor_id)
            L.circleMarker(point, {
              pane: DONOR_MARKER_PANE,
              radius: 5, color: '#fff', weight: 1.5, fillColor: '#7c3aed', fillOpacity: 0.95,
            })
              .bindPopup(
                `<b>Hồ sơ ${bloodType}</b><br>` +
                `<small>Bấm chấm để xem hồ sơ mock bên dưới bản đồ. Vị trí chấm chỉ đại diện ô H3, không phải GPS cá nhân.</small>`,
              )
              .bindTooltip(`Người hiến ${index + 1} · ${donor.blood_type}`, { direction: 'top' })
              .on('click', () => setSelectedDonorId(donor.donor_id))
              .addTo(layer)
          })
        } else {
          L.circleMarker([cell.lat, cell.lon], {
            pane: DONOR_MARKER_PANE,
            radius: 8 + Math.min(Math.sqrt(cell.count) * 2, 13),
            color: '#fff', weight: 2, fillColor: '#7c3aed', fillOpacity: 0.92,
          })
            .bindTooltip(`${cell.count} người hiến ${bloodType} · bấm để xem chấm`, { direction: 'top' })
            .on('click', () => {
              setExpandedDonorCell(cell.h3_cell)
              const map = mapRef.current
              if (map) map.setView([cell.lat, cell.lon], Math.max(map.getZoom(), 14))
            })
          .addTo(layer)
        }
      }

      for (const cell of (acceptedDonorCellsQuery.data ?? []) as AcceptedDonorCell[]) {
        L.circleMarker([cell.lat, cell.lon], {
          pane: DONOR_MARKER_PANE,
          radius: 10,
          color: '#fff',
          weight: 2,
          fillColor: '#0891b2',
          fillOpacity: 0.98,
        })
          .bindTooltip(`${cell.count} người hiến đã nhận lời · vùng H3`, { direction: 'top' })
          .bindPopup('<b>Người hiến đã nhận lời</b><br>' +
            `${cell.count} người trong ô H3 ~1 km<br>` +
            '<small>Vị trí ô lưới đại diện, không phải GPS thời gian thực.</small>')
          .addTo(layer)
      }

      for (const location of sharedResponderLocationsQuery.data ?? []) {
        L.circleMarker([location.latitude, location.longitude], {
          pane: DONOR_MARKER_PANE,
          radius: 9,
          color: '#fff',
          weight: 2,
          fillColor: '#0891b2',
          fillOpacity: 1,
        })
          .bindTooltip('Người hiến đã chủ động chia sẻ vị trí', { direction: 'top' })
          .bindPopup('<b>Vị trí đã được chia sẻ theo đồng ý</b><br>' +
            '<small>Chỉ cơ sở phát lời mời SOS xem được; chia sẻ tự hết hạn sau 4 giờ hoặc có thể thu hồi.</small>')
          .addTo(layer)
      }
    }

    // Facility markers show available compatible stock for the selected type.
    if (showStock) {
      for (const f of facilities as Facility[]) {
        const count = stockByFacility.get(f.id) ?? 0
        L.circleMarker([f.lat, f.lon], {
          radius: 9 + Math.min(Math.sqrt(count), 13),
          color: f.id === destinationId ? '#1d4ed8' : '#fff',
          weight: f.id === destinationId ? 4 : 2,
          fillColor: stockColor(count),
          fillOpacity: 0.92,
        })
          .bindPopup(
            `<b>${f.name}</b><br>` +
            `${bloodType} · ${COMPONENT_LABELS[component] ?? component}: ` +
            `<b>${count}</b> đơn vị — ${stockLabel(count)}<br>` +
            `<small>Chỉ đếm đơn vị còn hạn. Bấm ghim để chọn làm điểm nhận.</small>`,
          )
          .on('click', () => {
            setDestinationId(f.id)
            setSourceId('')
          })
          .addTo(layer)
      }
    }

    // Lớp 2 — ca đang cần, vẽ SAU CÙNG để luôn nằm trên
    //
    // GOM theo cơ sở, một ghim cho mỗi bệnh viện. Một bệnh viện có thể đang mở
    // nhiều ca cùng lúc; ghim từng ca đúng vào toạ độ cơ sở thì chúng chồng
    // khít và người điều phối tưởng nơi đó chỉ có một ca. Rải ra quanh cơ sở
    // cũng không ổn — làm vậy là đặt ca vào chỗ nó không nằm ở đó.
    if (showSos) {
      const byFacility = new Map<string, SosEvent[]>()
      for (const ev of activeSosEvents as SosEvent[]) {
        if (!ev.facility_id) continue
        const list = byFacility.get(ev.facility_id) ?? []
        list.push(ev)
        byFacility.set(ev.facility_id, list)
      }

      for (const [facilityId, list] of byFacility) {
        const f = facById.get(facilityId)
        if (!f) continue

        const emergency = list.some(e => e.urgency === 'emergency')
        const label = list.length === 1
          ? `${list[0].abo ?? ''}${list[0].rh ?? ''}`
          : `${list.length} ca`

        const lines = list
          .map(e => {
            const urgent = e.urgency === 'emergency' ? ' · <b style="color:#dc2626">CẤP CỨU</b>' : ''
            const comp = COMPONENT_LABELS[e.component_code ?? ''] ?? e.component_code ?? ''
            return `<li><b>${e.abo ?? ''}${e.rh ?? ''}</b> — ${comp}<br>` +
                   `<small>vòng ${e.ring} · nhận lời ${e.accept_count}/${e.target_count}${urgent}</small></li>`
          })
          .join('')

        L.marker([f.lat, f.lon], {
          icon: L.divIcon({
            className: 'sos-pin',
            html:
              `<div class="sos-pin-dot${emergency ? ' sos-pin-emergency' : ''}">${label}</div>`,
            iconSize: [34, 34],
            iconAnchor: [17, 17],
          }),
        })
          .bindPopup(
            `<b>${f.name}</b><br>` +
            `<span style="color:#dc2626;font-weight:600">Đang cần máu — ${list.length} ca</span>` +
            `<ul style="margin:6px 0 0;padding-left:17px">${lines}</ul>`,
          )
          .addTo(layer)
      }
    }

    const pickupGeometry = pickupRoute?.geometry
    if (showDonors && pickupRoute && pickupGeometry && pickupGeometry.length > 1
      && ['road', 'straight_line'].includes(pickupRoute.routing_mode)) {
      const isRoadPickupRoute = pickupRoute.routing_mode === 'road'
      L.polyline(pickupGeometry, {
        color: isRoadPickupRoute ? '#0891b2' : '#d97706',
        weight: 4,
        opacity: 0.9,
        dashArray: isRoadPickupRoute ? '8 6' : '10 8',
      })
        .bindPopup(`<b>${isRoadPickupRoute ? 'Đường tới người hiến đã đồng ý chia sẻ' : 'Đường thẳng tham khảo tới người hiến'}</b><br>${pickupRoute.duration_min.toFixed(1)} phút · ${(pickupRoute.distance_m / 1000).toFixed(1)} km`)
        .addTo(layer)
    }
  }, [mapReady, facilities, stockByFacility, activeSosEvents, density, acceptedDonorCellsQuery.data, sharedResponderLocationsQuery.data, mapDonorSearch.data, bloodType, component, showStock, showDonors, showSos, expandedDonorCell, routeEta, pickupRoute, sourceFacility, routeDestinationFacility, destinationId])

  const totalStock = useMemo(
    () => [...stockByFacility.values()].reduce((a, b) => a + b, 0),
    [stockByFacility],
  )
  const donorTotal = (density?.cells ?? []).reduce((a, c) => a + c.count, 0)
  const selectedDonor = selectedDonorProfile.data as Donor | undefined
  const selectedDonorEligible = selectedDonor
    ? component === 'PLT'
      ? selectedDonor.eligible_plt_plasma
      : component === 'RBC'
        ? selectedDonor.eligible_wb_rbc
        : selectedDonor.eligible
    : false

  return (
    <>
      <h2>Bản đồ điều phối</h2>
      <p className="subtitle">
        Tìm nguồn máu, phát yêu cầu điều chuyển và theo dõi SOS ngay trên bản đồ
      </p>
      {import.meta.env.DEV && <div className="map-workflow-actions" style={{ marginBottom: 16 }}>
        <a className="btn btn-secondary" href="http://127.0.0.1:5175/" target="_blank" rel="noreferrer">Mở cửa sổ bệnh viện ↗</a>
        <a className="btn btn-secondary" href="http://127.0.0.1:5176/" target="_blank" rel="noreferrer">Mở cửa sổ người dân ↗</a>
      </div>}

      {[
        { label: 'Danh sách bệnh viện', error: facilitiesQuery.error, retry: facilitiesQuery.refetch },
        { label: 'Tồn kho máu', error: stockQuery.error, retry: stockQuery.refetch },
        { label: 'Ca SOS', error: eventsQuery.error, retry: eventsQuery.refetch },
        { label: 'Mật độ người hiến', error: densityQuery.error, retry: densityQuery.refetch },
      ].filter(item => item.error).map(({ label, error, retry }) => (
        <div className="card" role="alert" key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, borderColor: 'var(--bb-red)' }}>
          <span>{label}: {error?.message ?? 'Không tải được dữ liệu.'}</span>
          <button className="btn btn-secondary" onClick={() => void retry()}>Thử tải lại</button>
        </div>
      ))}

      <div className="card">
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 14 }}>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Nhóm máu ABO</label>
            <select value={abo} onChange={e => setAbo(e.target.value)}>
              {ABO_OPTIONS.map(a => <option key={a} value={a}>Nhóm {a}</option>)}
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>RhD</label>
            <select value={rh} onChange={e => setRh(e.target.value)}>
              <option value="">Chưa rõ RhD</option>
              <option value="+">RhD⁺</option>
              <option value="-">RhD⁻ (hiếm, ~0,1%)</option>
            </select>
          </div>
          <div className="form-group" style={{ marginBottom: 0 }}>
            <label>Chế phẩm</label>
            <select value={component} onChange={e => setComponent(e.target.value)}>
              <option value="RBC">Khối hồng cầu</option>
              <option value="PLT">Khối tiểu cầu</option>
              <option value="FFP">Huyết tương tươi đông lạnh</option>
            </select>
          </div>
        </div>
      </div>

      <div className="card map-workflow-card">
        <div className="map-route-controls">
          <div className="map-route-status" aria-live="polite">
            {routeLoading ? 'Đang lấy tuyến đường…' : routeEta ? (
              routeEta.geometry && routeEta.geometry.length > 1 && routeEta.routing_mode === 'road'
                ? <><strong>{routeEta.duration_min.toFixed(1)} phút</strong> · {(routeEta.distance_m / 1000).toFixed(1)} km · {routeEta.provider}</>
                : routeEta.geometry && routeEta.geometry.length > 1 && routeEta.routing_mode === 'straight_line'
                  ? <><strong>~{routeEta.duration_min.toFixed(1)} phút</strong> · {(routeEta.distance_m / 1000).toFixed(1)} km · Đường thẳng tham khảo, OSRM không khả dụng</>
                  : <span role="alert">Dịch vụ chưa trả về hình học tuyến đường.</span>
            ) : routeError ? (
              <span role="alert">{routeError instanceof Error ? routeError.message : 'Không lấy được tuyến đường bộ từ OSRM.'}</span>
            ) : sourceId && routeDestinationFacility && sourceId === routeDestinationFacility.id ? (
              'Chọn hai cơ sở khác nhau để xem tuyến.'
            ) : (
              'Bấm ghim bệnh viện để chọn điểm nhận; chọn “Vẽ tuyến” trong kết quả điều chuyển để hiện đường đi.'
            )}
            {routeDestinationFacility && <span style={{ marginLeft: 8 }}>Điểm nhận: <strong>{routeDestinationFacility.name}</strong></span>}
          </div>
        </div>
        <div className="map-workflow-actions">
          <button className={`btn ${workflow === 'dispatch' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => {
              if (workflow === 'dispatch') setWorkflow(null)
              else { setWorkflow('dispatch'); setMatchResult(null); setDispatchRun(null); setSourceId('') }
            }}>
            Điều phối nguồn máu
          </button>
          <button className={`btn ${workflow === 'sos' ? 'btn-primary' : 'btn-secondary'}`}
            onClick={() => { setWorkflow(workflow === 'sos' ? null : 'sos'); setOpenedSos(null) }}>
            SOS thủ công
          </button>
          <div className="map-layer-toggles" role="group" aria-label="Lớp bản đồ">
            <label><input type="checkbox" checked={showStock} onChange={e => setShowStock(e.target.checked)} /> Kho</label>
            <label><input type="checkbox" checked={showDonors} onChange={e => {
              setShowDonors(e.target.checked)
              if (!e.target.checked) setExpandedDonorCell(null)
            }} /> Người hiến</label>
            <label><input type="checkbox" checked={showSos} onChange={e => setShowSos(e.target.checked)} /> SOS</label>
          </div>
        </div>

        {!!session?.facilityId && !!incomingOffers?.length && (
          <section className="card" aria-label="Yêu cầu điều chuyển đến cơ sở" style={{ margin: '0 0 14px', background: 'var(--surface-muted, var(--bg-subtle))' }}>
            <h3 style={{ marginTop: 0 }}>Yêu cầu điều chuyển đang chờ cơ sở của bạn</h3>
            <p style={{ marginTop: 0, color: 'var(--text-muted)', fontSize: 12.5 }}>
              Nhận hỗ trợ sẽ giữ các đơn vị tương hợp trong kho; từ chối hoặc hết hạn sẽ chuyển yêu cầu sang bước SOS nếu còn thiếu.
            </p>
            <div style={{ display: 'grid', gap: 8 }}>
              {incomingOffers.map(offer => (
                <div key={offer.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', padding: 10, border: '1px solid var(--border-color, #ddd)', borderRadius: 8 }}>
                  <div>
                    <strong>{offer.requester_facility_name}</strong> cần {offer.offered_qty} / {offer.qty} đơn vị {offer.abo}{offer.rh} · {COMPONENT_LABELS[offer.component_code] ?? offer.component_code}
                    <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Hạn phản hồi: {new Date(offer.expires_at).toLocaleTimeString('vi-VN')} · ưu tiên #{offer.priority_rank}</div>
                  </div>
                  <div style={{ display: 'flex', gap: 8 }}>
                    <button className="btn btn-primary" disabled={respondToOffer.isPending}
                      onClick={() => respondToOffer.mutate({ offerId: offer.id, accept: true, sourceFacilityId: offer.source_facility_id! })}>Nhận hỗ trợ</button>
                    <button className="btn btn-secondary" disabled={respondToOffer.isPending}
                      onClick={() => respondToOffer.mutate({ offerId: offer.id, accept: false, sourceFacilityId: offer.source_facility_id! })}>Từ chối</button>
                  </div>
                </div>
              ))}
            </div>
            {respondToOffer.error && <p role="alert" style={{ color: 'var(--bb-red)', marginBottom: 0 }}>{respondToOffer.error.message}</p>}
          </section>
        )}
        {session?.facilityId && incomingOffersError && (
          <p role="alert" style={{ color: 'var(--bb-red)', margin: 0 }}>
            Không tải được yêu cầu điều chuyển đến: {incomingOffersError.message}. Hãy khởi động lại bb-core để nạp API điều chuyển mới.
          </p>
        )}

        {trackableSosEvents.length > 0 && !sosTrackingEnabled && <section className="card" aria-label="Theo dõi ca SOS">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <span role="status">Đã tắt theo dõi chi tiết. Các tín hiệu SOS vẫn tiếp tục trên bản đồ.</span>
            <button className="btn btn-secondary" type="button" onClick={resumeSosTracking}>Theo dõi lại ca SOS</button>
          </div>
        </section>}

        {trackedSosEvent && <section className="card" aria-label="Điều khiển vòng SOS trên bản đồ">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <div>
              <strong>{trackedSosEvent.status === 'fulfilled' ? 'SOS đã đủ người nhận lời · chờ hoàn tất ca' : trackedSosEvent.status === 'expired' ? 'Đang theo dõi ca SOS đã kết thúc' : 'Đang theo dõi 1 ca SOS'}</strong>
              <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Các ca SOS khác vẫn nằm trong lịch sử.</div>
            </div>
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              <button className="btn btn-secondary" type="button" onClick={stopSosTracking}>Tắt theo dõi</button>
              {canManageTrackedSos && (
                <button
                  className="btn btn-danger"
                  type="button"
                  disabled={completeSos.isPending || !canCompleteTrackedSos}
                  onClick={() => {
                    if (window.confirm('Đánh dấu ca SOS đã hoàn tất? Ca sẽ ngừng mời người hiến và vẫn được lưu trong lịch sử.')) {
                      completeSos.mutate(trackedSosEvent.id)
                    }
                  }}
                >
                  {completeSos.isPending ? 'Đang hoàn tất…' : 'Hoàn tất ca SOS'}
                </button>
              )}
              <Link className="btn btn-secondary" to={`/sos?eventId=${encodeURIComponent(trackedSosEvent.id)}`}>
              Mở màn SOS và các vòng →
              </Link>
            </div>
          </div>
          {canManageTrackedSos && !canCompleteTrackedSos && (
            <p role="status" style={{ color: 'var(--text-muted)', fontSize: 12.5, marginBottom: 0 }}>
              {!['fulfilled', 'expired'].includes(trackedSosEvent.status)
                ? 'Ca cần dừng tuyển người hiến trước khi hoàn tất.'
                : trackedSosRespondersQuery.data === undefined || trackedSosRewardsQuery.data === undefined
                  ? 'Đang tải xác nhận hiến và phương án hỗ trợ.'
                  : `Còn ${trackedPendingFollowups} người nhận lời cần xử lý trước khi hoàn tất.`}
            </p>
          )}
          {completeSos.error && <p role="alert" style={{ color: 'var(--bb-red)', marginBottom: 0 }}>{completeSos.error.message}</p>}
          <details style={{ marginTop: 12 }}>
            <summary style={{ cursor: 'pointer', fontWeight: 650, padding: '8px 0' }}>Vòng SOS · đếm ngược và điều khiển thủ công</summary>
          <div style={{ display: 'grid', gap: 10 }}>
            {[trackedSosEvent].map(event => {
              const seconds = secondsUntilNextRing(event, clockNow)
              const finalSeconds = secondsUntilFinalTimeout(
                event,
                trackedSosNotificationsQuery.data ?? [],
                clockNow,
              )
              const countdownSeconds = event.status === 'open' ? finalSeconds ?? seconds : null
              const countdownLabel = event.status === 'fulfilled'
                ? 'Đã đủ người nhận lời'
                : event.status === 'expired'
                  ? 'Ca đã kết thúc'
                  : event.ring >= 3
                ? finalSeconds == null
                  ? 'Đang tải thời hạn cuối'
                  : finalSeconds === 0
                    ? 'Đang chờ máy chủ kết thúc ca'
                    : 'Tự đóng nếu chưa có người nhận'
                : seconds == null ? 'Đã đến vòng cuối' : `Tới vòng ${event.ring + 1}`
              return <div key={event.id} style={{ display: 'grid', gridTemplateColumns: 'minmax(220px, 1fr) auto auto', alignItems: 'center', gap: 12, padding: 12, border: '1px solid var(--border-color, #ddd)', borderRadius: 9 }}>
                <div>
                  <strong>{event.abo ?? ''}{event.rh ?? ''} · vòng {event.ring} / 3</strong>
                  <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Ca {event.id} · đã có {event.accept_count}/{event.target_count} người đồng ý</div>
                  <div style={{ display: 'flex', gap: 6, marginTop: 8 }} aria-label="Các vòng 0 đến 3">
                    {SOS_RING_START_MINUTES.map((minute, ring) => <span key={ring} style={{ padding: '3px 8px', borderRadius: 999, background: ring === event.ring ? 'var(--bb-blue-soft)' : 'var(--surface-muted, #f3f4f6)', color: ring === event.ring ? 'var(--bb-blue)' : 'var(--text-muted)', fontSize: 11, fontWeight: 650 }}>
                      {ring} · {minute === 0 ? 'T+0' : `T+${minute}`}
                    </span>)}
                  </div>
                </div>
                <div style={{ minWidth: 150, textAlign: 'center' }}>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{countdownLabel}</div>
                  <strong style={{ fontVariantNumeric: 'tabular-nums', fontSize: 20 }}>{countdownSeconds == null ? '—' : formatCountdown(countdownSeconds)}</strong>
                </div>
                {event.status === 'open' && <button className="btn btn-secondary" disabled={event.ring >= 3 || advanceSos.isPending}
                  onClick={() => advanceSos.mutate(event.id)}>
                  {event.ring >= 3 ? 'Vòng cuối' : `Chuyển sang vòng ${event.ring + 1}`}
                </button>}
              </div>
            })}
          </div>
          {advanceSos.isPending && <p role="status" style={{ marginBottom: 0 }}>Đang chuyển vòng SOS…</p>}
          {advanceSos.error && <p role="alert" style={{ color: 'var(--bb-red)', marginBottom: 0 }}>{advanceSos.error.message}</p>}
          </details>
        </section>}

        {workflow === 'dispatch' && (
          <section className="card" aria-label="Điều phối điều chuyển máu" style={{ margin: 0, background: 'var(--surface-muted, var(--bg-subtle))' }}>
            <h3 style={{ marginTop: 0 }}>Tìm nguồn và phát yêu cầu điều chuyển</h3>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(155px, 1fr))', gap: 12 }}>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Số đơn vị</label>
                <input type="number" min={1} max={500} value={matchQty} onChange={e => setMatchQty(Math.min(500, Math.max(1, Number(e.target.value))))} />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Mức khẩn cấp</label>
                <select value={matchUrgency} onChange={e => setMatchUrgency(e.target.value)}>
                  {Object.entries(URGENCY_LABELS).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}
                </select>
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Cần trước</label>
                <input type="datetime-local" value={neededBy} onChange={e => setNeededBy(e.target.value)} />
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Giới tính người nhận (RhD)</label>
                <select value={recipientSex} onChange={e => setRecipientSex(e.target.value)}>
                  <option value="">Chưa rõ</option><option value="M">Nam</option><option value="F">Nữ</option>
                </select>
              </div>
              <div className="form-group" style={{ marginBottom: 0 }}>
                <label>Tuổi người nhận</label>
                <input type="number" min={0} max={120} value={recipientAge} placeholder="Tuổi" onChange={e => setRecipientAge(e.target.value)} />
              </div>
            </div>
            <p style={{ color: 'var(--text-muted)', fontSize: 12.5, margin: '10px 0' }}>
              Hệ thống dùng giới tính và tuổi người nhận cho quy tắc RhD. Khi RhD chưa rõ, phụ nữ 18–45 tuổi được xử lý như RhD âm; các trường hợp khác như RhD dương. Đây là thông tin an toàn của người nhận, không phải bộ lọc giới tính người hiến.
            </p>
            <button className="btn btn-primary" disabled={!destinationFacility || matchSearch.isPending}
              onClick={() => matchSearch.mutate()}>
              {matchSearch.isPending ? 'Đang xếp kho và gửi yêu cầu…' : `Phát yêu cầu điều chuyển ${bloodType}`}
            </button>
            {matchSearch.error && <p role="alert" style={{ color: 'var(--bb-red)', marginBottom: 0 }}>{matchSearch.error.message}</p>}
            {matchResult && (
              <div style={{ marginTop: 14 }}>
                <strong>{matchResult.compatible_count} đơn vị tương hợp</strong> trong {matchResult.total_candidates} đơn vị được xét. Hệ thống đã phát lời mời tới các cơ sở có tồn kho chia sẻ an toàn.
                <p style={{ color: 'var(--text-muted)', fontSize: 12.5, margin: '8px 0' }}>
                  Hạn vàng được tính từ thời điểm cần máu trừ ETA nhanh nhất ({dispatchRun?.fastestEtaSeconds == null ? 'dự phòng 30 phút khi API chưa có ETA' : `${Math.ceil(dispatchRun.fastestEtaSeconds / 60)} phút`}), 45 phút cho bốn vòng SOS và 15 phút dự phòng vận chuyển/điều phối; giới hạn chờ là 5 phút (cấp cứu), 10 phút (khẩn) hoặc 20 phút (thường quy). Nếu không còn thời gian an toàn, SOS bắt đầu ngay.
                </p>
                {dispatchRun && <div style={{ margin: '12px 0', padding: 12, borderRadius: 8, borderLeft: '4px solid', borderColor: dispatchPhase === 'waiting' ? '#eab308' : dispatchPhase === 'fulfilled' ? '#16a34a' : '#dc2626', background: dispatchPhase === 'waiting' ? '#fefce8' : dispatchPhase === 'fulfilled' ? '#f0fdf4' : '#fef2f2' }}>
                  {dispatchPhase === 'waiting' && <strong>Đang chờ phản hồi — còn {Math.floor(yellowSecondsLeft / 60)}:{String(yellowSecondsLeft % 60).padStart(2, '0')}</strong>}
                  {dispatchPhase === 'sos_pending' && <strong>Không còn bệnh viện chờ phản hồi — hệ thống đang tự mở SOS người hiến.</strong>}
                  {dispatchPhase === 'sos' && (linkedSos?.status === 'completed'
                    ? <strong>Ca SOS đã hoàn tất.</strong>
                    : linkedSos?.status === 'fulfilled'
                      ? <strong>SOS đã nhận đủ người đồng ý · {linkedSos.accept_count}/{linkedSos.target_count}. Mở hồ sơ để cơ sở xác nhận hiến thật.</strong>
                      : linkedSos?.status === 'expired'
                        ? <strong>Ca SOS đã kết thúc ở vòng {linkedSos.ring}; có {linkedSos.accept_count}/{linkedSos.target_count} người đồng ý.</strong>
                        : <strong>SOS người hiến đã bắt đầu · vòng {linkedSos?.ring ?? 0} · đã gửi {linkedSos?.donors_notified ?? 0} lời mời.</strong>)}
                  {dispatchPhase === 'sos' && linkedSos && <Link to={`/sos?eventId=${encodeURIComponent(linkedSos.id)}`}>Mở dashboard xác nhận hiến →</Link>}
                  {dispatchPhase === 'fulfilled' && <strong>Đã nhận đủ {acceptedQty} đơn vị điều chuyển; SOS không cần thiết.</strong>}
                  {dispatchPhase === 'sos' && linkedSos?.message && <div style={{ marginTop: 4 }}>{linkedSos.message}</div>}
                  {dispatchPhase === 'sos_pending' && <div style={{ marginTop: 4 }}>Nếu đã có một phần nguồn, SOS chỉ gọi cho số đơn vị còn thiếu. Bộ lập lịch kiểm tra tối đa mỗi 30 giây.</div>}
                </div>}
                {dispatchPhase === 'sos_pending' && openSos.error && (
                  <p role="alert" style={{ color: 'var(--bb-red)', marginBottom: 0 }}>
                    Không mở được SOS người hiến: {openSos.error.message}. Hãy kiểm tra backend local ở cổng 8000 rồi thử lại từ mục SOS.
                  </p>
                )}
                {!!transferOffers?.length && <div style={{ overflowX: 'auto', marginTop: 8 }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13 }}>
                    <thead><tr><th align="left">Ưu tiên</th><th align="left">Cơ sở</th><th align="left">Kho chia sẻ an toàn</th><th align="left">Trạng thái</th><th align="left">Tuyến</th></tr></thead>
                    <tbody>{[...(transferOffers ?? [])].sort((a: TransferOffer, b: TransferOffer) => a.priority_rank - b.priority_rank).map(offer => (
                      <tr key={offer.id} style={{ borderTop: '1px solid var(--border-color, #ddd)' }}>
                        <td style={{ padding: '8px 6px' }}>#{offer.priority_rank}</td>
                        <td style={{ padding: '8px 6px' }}>{offer.source_facility_name}</td>
                        <td style={{ padding: '8px 6px' }}><span style={{ display: 'inline-block', borderRadius: 12, padding: '2px 8px', color: '#fff', background: stockColor(offer.available_qty) }}>{offer.available_qty} đơn vị · {stockLabel(offer.available_qty)}</span></td>
                        <td style={{ padding: '8px 6px' }}>{offer.status === 'pending' ? 'Đang chờ' : offer.status === 'accepted' ? `Đã nhận ${offer.accepted_qty}` : offer.status === 'declined' ? 'Từ chối' : offer.status === 'expired' ? 'Hết hạn' : offer.status === 'cancelled' ? 'Đã đủ số lượng' : 'Không có nguồn'}</td>
                        <td style={{ padding: '8px 6px' }}>{(offer.accepted_qty ?? 0) > 0 && offer.source_facility_id && offer.source_facility_id !== routeDestinationFacility?.id
                          ? <button className="btn btn-secondary" disabled={!routeDestinationFacility || routeLoading} onClick={() => { setDestinationId(dispatchRun?.destinationFacilityId ?? destinationId); setSourceId(offer.source_facility_id!); setShowStock(true); setRouteRequestVersion(version => version + 1) }}>Vẽ tuyến</button>
                          : offer.status === 'pending' ? 'Chờ bệnh viện phản hồi'
                            : offer.status === 'accepted' ? 'Đã nhận hỗ trợ'
                              : offer.source_facility_id === routeDestinationFacility?.id ? 'Cùng cơ sở nhận' : '—'}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>}
                {dispatchPhase === 'sos' && <p style={{ marginBottom: 0, fontSize: 12.5, color: 'var(--text-muted)' }}>
                  SOS tự leo thang bốn vòng ở T+0, T+10, T+25 và T+45 phút; danh sách mời không gọi trùng người giữa các vòng.
                </p>}
              </div>
            )}
          </section>
        )}

        {workflow === 'sos' && (
          <section className="card" aria-label="Mở SOS máu" style={{ margin: 0, background: 'var(--surface-muted, var(--bg-subtle))' }}>
            <h3 style={{ marginTop: 0 }}>Mở SOS từ bản đồ</h3>
            <p style={{ color: 'var(--text-muted)', fontSize: 12.5, marginTop: 0 }}>
              SOS gửi lời mời theo vòng tới người hiến đủ điều kiện; quy trình lựa chọn và xác nhận hiến được cơ sở điều phối theo dõi.
            </p>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(155px, 1fr))', gap: 12 }}>
              <div className="form-group" style={{ marginBottom: 0 }}><label>Số đơn vị cần</label>
                <input type="number" min={1} max={20} value={sosQty} onChange={e => setSosQty(Math.max(1, Number(e.target.value)))} /></div>
              <div className="form-group" style={{ marginBottom: 0 }}><label>Mức khẩn cấp</label>
                <select value={sosUrgency} onChange={e => setSosUrgency(e.target.value)}>
                  {Object.entries(URGENCY_LABELS).map(([key, value]) => <option key={key} value={key}>{value.label} — {value.desc}</option>)}
                </select></div>
            </div>
            <button className="btn btn-primary" style={{ marginTop: 12 }} disabled={!destinationFacility || !rh || openSos.isPending}
              onClick={() => openSos.mutate({})}>{openSos.isPending ? 'Đang gửi SOS…' : `Gửi SOS ${bloodType}`}</button>
            {!rh && <p role="note" style={{ color: 'var(--text-muted)', fontSize: 12.5 }}>SOS độc lập cần biết RhD để chọn người hiến an toàn. Hãy xác nhận RhD hoặc dùng luồng tìm nguồn điều chuyển.</p>}
            {openSos.error && <p role="alert" style={{ color: 'var(--bb-red)' }}>{openSos.error.message}</p>}
            {displayedOpenedSos && <div role="status" style={{ marginTop: 12, padding: 12, borderRadius: 8, background: 'var(--bb-green-soft, #f0fdf4)' }}>
              <strong>{displayedOpenedSos.status === 'completed' ? 'Ca SOS đã hoàn tất' : displayedOpenedSos.status === 'fulfilled' ? 'SOS đã đủ người đồng ý' : displayedOpenedSos.status === 'expired' ? 'SOS đã kết thúc' : 'SOS đang mở'}</strong>
              {' · '}{displayedOpenedSos.accept_count}/{displayedOpenedSos.target_count} người đồng ý
              {displayedOpenedSos.status === 'open' && <> · đã gửi {displayedOpenedSos.donors_notified} lời mời · vòng {displayedOpenedSos.ring}</>}
              {displayedOpenedSos.message && displayedOpenedSos.status === 'open' && <div>{displayedOpenedSos.message}</div>}
              <small>Mã sự kiện: {displayedOpenedSos.id}</small>
            </div>}
          </section>
        )}
      </div>

      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
          Tồn kho: {metricFreshness(stockQuery.dataUpdatedAt, stockQuery.isFetching)} · Ca SOS: {metricFreshness(openEventsQuery.dataUpdatedAt || eventsQuery.dataUpdatedAt, openEventsQuery.isFetching || eventsQuery.isFetching)} · Người hiến: {metricFreshness(densityQuery.dataUpdatedAt, densityQuery.isFetching)}
        </span>
        <button className="btn btn-secondary" type="button" onClick={() => void refreshMapStats()} disabled={statsRefreshing}>
          <RefreshCw size={14} /> {statsRefreshing ? 'Đang cập nhật…' : 'Cập nhật số liệu'}
        </button>
      </div>
      <div className="stat-grid">
        <div className="stat-card">
          <div className="stat-number">{stockQuery.isError ? '—' : stockQuery.isLoading ? '…' : totalStock}</div>
          <div className="stat-label">Đơn vị {bloodType} còn hạn</div>
        </div>
        <div className="stat-card">
          <div className="stat-number">{openEventsQuery.isError && eventsQuery.isError ? '—' : activeSosEvents.length}</div>
          <div className="stat-label">Ca đang cần máu</div>
        </div>
        <div className="stat-card">
          <div className="stat-number">{densityQuery.isError ? '—' : densityQuery.isLoading ? '…' : donorTotal}</div>
          <div className="stat-label">Người hiến {bloodType} trong vùng</div>
        </div>
        <div className="stat-card">
          <div className="stat-number">{densityQuery.isError ? '—' : densityQuery.isLoading ? '…' : density?.cells.length ?? 0}</div>
          <div className="stat-label">Ô lưới có người hiến</div>
        </div>
      </div>

      <div className="card" style={{ padding: 0, overflow: 'hidden' }}>
        <div ref={boxRef} className={dark ? 'bb-map bb-map-dark' : 'bb-map'}
             style={{ height: 560, width: '100%' }} />
      </div>

      {showDonors && mapDonorSearch.isLoading && (
        <div className="card" role="status">Đang tải hồ sơ người hiến mô phỏng để gắn vào các chấm trên bản đồ…</div>
      )}
      {showDonors && mapDonorSearch.error && (
        <div className="card" role="alert" style={{ color: 'var(--bb-red)' }}>
          Không tải được hồ sơ người hiến cho bản đồ: {mapDonorSearch.error.message}
        </div>
      )}
      {selectedDonorId && (
        <div className="card" aria-label="Hồ sơ người hiến được chọn">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 }}>
            <div>
              <h3 style={{ marginTop: 0, marginBottom: 4 }}>Hồ sơ người hiến</h3>
              {selectedDonorId.startsWith('mock-map-') && (
                <span style={{ display: 'inline-block', padding: '3px 8px', borderRadius: 20, background: '#ede9fe', color: '#6d28d9', fontSize: 11, fontWeight: 700 }}>
                  DỮ LIỆU MÔ PHỎNG
                </span>
              )}
            </div>
            <button className="btn btn-secondary" onClick={() => setSelectedDonorId(null)}>Đóng hồ sơ</button>
          </div>
          {selectedDonorProfile.isLoading && <p>Đang tải chi tiết hồ sơ…</p>}
          {selectedDonorProfile.error && <p role="alert" style={{ color: 'var(--bb-red)' }}>{selectedDonorProfile.error.message}</p>}
          {selectedDonor && <>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 12, marginTop: 14 }}>
              <ProfileField label="Mã hồ sơ" value={selectedDonor.id} />
              <ProfileField label="Nhóm máu" value={selectedDonor.blood_type} />
              <ProfileField label="Giới tính" value={selectedDonor.sex === 'F' ? 'Nữ' : selectedDonor.sex === 'M' ? 'Nam' : 'Chưa có dữ liệu'} />
              <ProfileField label="Tuổi (mô phỏng)" value={selectedDonor.birth_year ? `${new Date().getFullYear() - selectedDonor.birth_year} tuổi` : 'Chưa có dữ liệu'} />
              <ProfileField label="Cân nặng" value={selectedDonor.weight_kg ? `${selectedDonor.weight_kg} kg` : 'Chưa có dữ liệu'} />
              <ProfileField label="Lần hiến gần nhất" value={selectedDonor.last_donation_at
                ? `${new Date(selectedDonor.last_donation_at).toLocaleDateString('vi-VN')} (${selectedDonor.days_since_donation ?? '—'} ngày trước)`
                : 'Chưa có dữ liệu'} />
              <ProfileField label="Xác minh" value={selectedDonor.verified ? 'Đã xác minh' : 'Chưa xác minh'} />
              <ProfileField label={`Điều kiện hiến (${component})`} value={selectedDonorEligible ? 'Đủ điều kiện theo dữ liệu mô phỏng' : selectedDonor.ineligible_reason ?? 'Chưa đủ điều kiện'} />
            </div>
            <p style={{ color: 'var(--text-muted)', fontSize: 12.5, marginBottom: 0, marginTop: 12 }}>
              Hồ sơ demo không có tên hoặc số điện thoại thật. Chấm trên bản đồ được đặt đại diện trong ô H3 khoảng 1,2 km; không phải GPS của người hiến.
            </p>
          </>}
        </div>
      )}

      <div className="card">
        <h3 style={{ marginTop: 0 }}>Đọc bản đồ</h3>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 18, fontSize: 13.5 }}>
          <Legend color="#15803d" text="Kho dồi dào (≥150)" />
          <Legend color="#65a30d" text="Đủ (60–149)" />
          <Legend color="#f59e0b" text="Thấp (20–59)" />
          <Legend color="#dc2626" text="Rất thấp (<20)" />
          <Legend color="#991b1b" text="Hết" />
          <Legend color="#7c3aed" text="Người hiến (bấm chấm để tách ra)" />
          <Legend color="#0891b2" text="Người hiến đã nhận lời SOS" />
        </div>
        <p style={{ fontSize: 12.5, color: 'var(--text-muted)', marginTop: 14, marginBottom: 0 }}>
          Chấm to nhỏ theo số đơn vị. Ghim vuông là ca đang cần máu — viền đỏ nhấp nháy nghĩa là cấp cứu.
          Chấm tím là số người hiến trong <b>ô H3 ~1,2 km</b>; bấm vào để bung các chấm đại diện ẩn danh trong vùng.
          Đây không phải vị trí thực tế: hệ thống chỉ lưu ô lưới, không lưu GPS cá nhân.
          {density && density.suppressed_cells > 0 && (
            <> Có <b>{density.suppressed_cells}</b> ô bị ẩn vì dưới ngưỡng {density.min_donors} người.</>
          )}
        </p>
      </div>
    </>
  )
}

function Legend({ color, text }: { color: string; text: string }) {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
      <span style={{ width: 14, height: 14, borderRadius: 4, background: color, flexShrink: 0 }} />
      {text}
    </span>
  )
}

function ProfileField({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ padding: 10, borderRadius: 8, background: 'var(--bb-gray-50, #f8fafc)' }}>
      <div style={{ color: 'var(--text-muted)', fontSize: 11.5, marginBottom: 4 }}>{label}</div>
      <strong style={{ fontSize: 13.5 }}>{value}</strong>
    </div>
  )
}
