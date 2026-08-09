"use client"

import React, {
  RefObject,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react"
import {
  motion,
  MotionValue,
  SpringOptions,
  useAnimationFrame,
  useMotionValue,
  useScroll,
  useSpring,
  useTransform,
  useVelocity,
} from "motion/react"

import { cn } from "@/lib/utils"

// Custom wrap function
const wrap = (min: number, max: number, value: number): number => {
  const range = max - min
  return ((((value - min) % range) + range) % range) + min
}

type PreserveAspectRatioAlign =
  | "none"
  | "xMinYMin"
  | "xMidYMin"
  | "xMaxYMin"
  | "xMinYMid"
  | "xMidYMid"
  | "xMaxYMid"
  | "xMinYMax"
  | "xMidYMax"
  | "xMaxYMax"

interface CSSVariableInterpolation {
  property: string
  from: number | string
  to: number | string
}

type PreserveAspectRatioMeetOrSlice = "meet" | "slice"

type PreserveAspectRatio =
  | PreserveAspectRatioAlign
  | `${Exclude<PreserveAspectRatioAlign, "none">} ${PreserveAspectRatioMeetOrSlice}`

interface MarqueeAlongSvgPathProps {
  children: React.ReactNode
  className?: string

  // Path properties
  path: string
  pathId?: string
  preserveAspectRatio?: PreserveAspectRatio
  showPath?: boolean

  // SVG properties
  width?: string | number
  height?: string | number
  viewBox?: string

  // Marquee properties
  baseVelocity?: number
  direction?: "normal" | "reverse"
  easing?: (value: number) => number
  slowdownOnHover?: boolean
  slowDownFactor?: number
  slowDownSpringConfig?: SpringOptions

  // Scroll properties
  useScrollVelocity?: boolean
  scrollAwareDirection?: boolean
  scrollSpringConfig?: SpringOptions
  scrollContainer?: RefObject<HTMLElement | null> | HTMLElement | null

  // Item repetition
  repeat?: number

  // Drag properties
  draggable?: boolean
  dragSensitivity?: number
  dragVelocityDecay?: number
  dragAwareDirection?: boolean
  grabCursor?: boolean

  // Z-index properties
  enableRollingZIndex?: boolean
  zIndexBase?: number
  zIndexRange?: number

  cssVariableInterpolation?: CSSVariableInterpolation[]

  // Responsive properties
  responsive?: boolean

  // Motion-budget properties
  respectReducedMotion?: boolean
  pauseWhenOffscreen?: boolean

  /* `offset-rotate` defaults to `auto`, turning each item to face along the
     path. That suits something with a natural orientation — a sheet of paper
     tumbling down a curve — but it wrecks an icon: a chart or gauge glyph tipped
     45° stops being readable as itself. Set false to keep items upright while
     they still travel the path. */
  followPathRotation?: boolean
}

/* The marquee advances inside a requestAnimationFrame loop rather than a CSS
   animation, so neither the global `prefers-reduced-motion` rule in globals.css
   nor the browser's own animation throttling can reach it. This hook is the
   component's own budget:

   - Reduced motion parks the loop entirely. The items stay evenly distributed
     along the path, so the composition still reads as "items on a curve" — the
     meaning survives, only the travel stops.
   - A decorative loop scrolled out of view, or sitting in a background tab, is
     pure battery cost. IntersectionObserver and the visibility event park it.

   It starts parked so the server render and the first client render agree, and
   because a parked marquee is already in its correct static composition. */
function useMarqueeActive(
  containerRef: RefObject<HTMLElement | null>,
  respectReducedMotion: boolean,
  pauseWhenOffscreen: boolean
) {
  const [reducedMotion, setReducedMotion] = useState(false)
  const [visible, setVisible] = useState(!pauseWhenOffscreen)

  useEffect(() => {
    if (!respectReducedMotion) {
      setReducedMotion(false)
      return
    }
    const query = window.matchMedia("(prefers-reduced-motion: reduce)")
    const sync = () => setReducedMotion(query.matches)
    sync()
    query.addEventListener("change", sync)
    return () => query.removeEventListener("change", sync)
  }, [respectReducedMotion])

  useEffect(() => {
    if (!pauseWhenOffscreen) {
      setVisible(true)
      return
    }
    const el = containerRef.current
    if (!el) return

    let onscreen = false
    const syncVisible = () => setVisible(onscreen && !document.hidden)

    const observer = new IntersectionObserver(
      ([entry]) => {
        onscreen = entry.isIntersecting
        syncVisible()
      },
      { rootMargin: "128px" }
    )
    observer.observe(el)
    document.addEventListener("visibilitychange", syncVisible)

    return () => {
      observer.disconnect()
      document.removeEventListener("visibilitychange", syncVisible)
    }
  }, [containerRef, pauseWhenOffscreen])

  return !reducedMotion && visible
}

/* Each item owns its own motion values, so it has to be a real component rather
   than a callback inside .map(). Hooks called straight from the loop would be
   re-ordered the moment `children` or `repeat` changed, which React reports as
   "rendered more hooks than during the previous render".
   `cssVariableInterpolation` is still read as a fixed-length list — treat it as a
   constant per mount, the way the rest of the props are used. */
interface MarqueeItemProps {
  child: React.ReactNode
  itemIndex: number
  itemCount: number
  repeatIndex: number
  path: string
  baseOffset: MotionValue<number>
  easing?: (value: number) => number
  enableRollingZIndex: boolean
  calculateZIndex: (offsetDistance: number) => number | undefined
  cssVariableInterpolation: CSSVariableInterpolation[]
  draggable: boolean
  grabCursor: boolean
  isActive: boolean
  followPathRotation: boolean
  onHoverChange: (hovered: boolean) => void
  itemRef: (el: HTMLDivElement | null) => void
}

const MarqueeItem = ({
  child,
  itemIndex,
  itemCount,
  repeatIndex,
  path,
  baseOffset,
  easing,
  enableRollingZIndex,
  calculateZIndex,
  cssVariableInterpolation,
  draggable,
  grabCursor,
  isActive,
  followPathRotation,
  onHoverChange,
  itemRef,
}: MarqueeItemProps) => {
  // Create a unique offset transform for each item
  const itemOffset = useTransform(baseOffset, (v) => {
    const position = (itemIndex * 100) / itemCount
    const wrappedValue = wrap(0, 100, v + position)
    return `${easing ? easing(wrappedValue / 100) * 100 : wrappedValue}%`
  })

  // Create a motion value for the current offset distance
  const currentOffsetDistance = useMotionValue(0)

  // Update z-index when offset distance changes
  const zIndex = useTransform(currentOffsetDistance, (value) =>
    calculateZIndex(value)
  )

  // Update current offset distance value when animation runs
  useEffect(() => {
    const unsubscribe = itemOffset.on("change", (value: string) => {
      // Parse percentage string to get numerical value
      const match = value.match(/^([\d.]+)%$/)
      if (match && match[1]) {
        currentOffsetDistance.set(parseFloat(match[1]))
      }
    })
    return unsubscribe
  }, [itemOffset, currentOffsetDistance])

  const cssVariables = Object.fromEntries(
    cssVariableInterpolation.map(({ property, from, to }) => [
      property,
      // eslint-disable-next-line react-hooks/rules-of-hooks
      useTransform(currentOffsetDistance, [0, 100], [from, to]),
    ])
  )

  return (
    <motion.div
      ref={itemRef}
      className={cn(
        "absolute top-0 left-0",
        draggable && grabCursor && "cursor-grab"
      )}
      style={{
        offsetPath: `path('${path}')`,
        offsetDistance: itemOffset,
        offsetRotate: followPathRotation ? undefined : "0deg",
        zIndex: enableRollingZIndex ? zIndex : undefined,
        // Only hint the compositor while the loop is actually running; a parked
        // marquee holding a layer per item is wasted memory.
        willChange: isActive ? "offset-distance" : undefined,
        backfaceVisibility: "hidden",
        ...cssVariables,
      }}
      aria-hidden={repeatIndex > 0}
      onMouseEnter={() => onHoverChange(true)}
      onMouseLeave={() => onHoverChange(false)}
    >
      {child}
    </motion.div>
  )
}

const MarqueeAlongSvgPath = ({
  children,
  className,

  // Path defaults
  path,
  pathId,
  preserveAspectRatio = "xMidYMid meet",
  showPath = false,

  // SVG defaults
  width = "100%",
  height = "100%",
  viewBox = "0 0 100 100",

  // Marquee defaults
  baseVelocity = 5,
  direction = "normal",
  easing,
  slowdownOnHover = false,
  slowDownFactor = 0.3,
  slowDownSpringConfig = { damping: 50, stiffness: 400 },

  // Scroll defaults
  useScrollVelocity = false,
  scrollAwareDirection = false,
  scrollSpringConfig = { damping: 50, stiffness: 400 },
  scrollContainer,

  // Items repetition
  repeat = 3,

  // Drag defaults
  draggable = false,
  dragSensitivity = 0.2,
  dragVelocityDecay = 0.96,
  dragAwareDirection = false,
  grabCursor = false,

  // Z-index defaults
  enableRollingZIndex = true,
  zIndexBase = 1, // Base z-index value
  zIndexRange = 10, // Range of z-index values to use

  cssVariableInterpolation = [],

  // Responsive defaults
  responsive = false,

  // Motion-budget defaults
  respectReducedMotion = true,
  pauseWhenOffscreen = true,

  followPathRotation = true,
}: MarqueeAlongSvgPathProps) => {
  const container = useRef<HTMLDivElement>(null)
  const marqueeContainerRef = useRef<HTMLDivElement>(null)
  const baseOffset = useMotionValue(0)

  const pathRef = useRef<SVGPathElement>(null)

  const itemRefs = useRef<Map<string, HTMLDivElement>>(new Map())

  // Responsive scaling using direct DOM manipulation (no re-renders)
  useEffect(() => {
    if (!responsive) return

    const [, , vbWidth, vbHeight] = viewBox.split(" ").map(Number)
    const originalWidth = vbWidth || 100
    const originalHeight = vbHeight || 100

    const updateScale = () => {
      const wrapper = container.current
      const marqueeContainer = marqueeContainerRef.current
      if (!wrapper || !marqueeContainer) return

      const wrapperWidth = wrapper.clientWidth
      const wrapperHeight = wrapper.clientHeight

      const scaleX = wrapperWidth / originalWidth
      const scaleY = wrapperHeight / originalHeight
      const scale = Math.min(scaleX, scaleY)

      // Calculate the scaled dimensions
      const scaledWidth = originalWidth * scale
      const scaledHeight = originalHeight * scale

      // Center the marquee container within the wrapper
      const offsetX = (wrapperWidth - scaledWidth) / 2
      const offsetY = (wrapperHeight - scaledHeight) / 2

      // Set fixed dimensions on the container
      marqueeContainer.style.width = `${originalWidth}px`
      marqueeContainer.style.height = `${originalHeight}px`

      // Apply scale and position to center
      marqueeContainer.style.transform = `translate(${offsetX}px, ${offsetY}px) scale(${scale})`
      marqueeContainer.style.transformOrigin = "top left"
    }

    updateScale()

    /* ResizeObserver rather than a window resize listener: the wrapper changes
       width without the window doing so — the sidebar collapsing, a phone's URL
       bar retracting, or the container reflowing at a breakpoint. A window-only
       listener leaves the marquee scaled to a stale box in all three cases. */
    const observer = new ResizeObserver(updateScale)
    if (container.current) observer.observe(container.current)
    return () => observer.disconnect()
  }, [responsive, viewBox])

  // Create an array of items outside of the render function
  const items = React.useMemo(() => {
    const childrenArray = React.Children.toArray(children)

    return childrenArray.flatMap((child, childIndex) =>
      Array.from({ length: repeat }, (_, repeatIndex) => {
        const itemIndex = repeatIndex * childrenArray.length + childIndex
        const key = `${childIndex}-${repeatIndex}`
        return {
          child,
          childIndex,
          repeatIndex,
          itemIndex,
          key,
        }
      })
    )
  }, [children, repeat])

  // Function to calculate z-index based on offset distance
  const calculateZIndex = useCallback(
    (offsetDistance: number) => {
      if (!enableRollingZIndex) {
        return undefined
      }

      // Simple progress-based z-index
      const normalizedDistance = offsetDistance / 100
      return Math.floor(zIndexBase + normalizedDistance * zIndexRange)
    },
    [enableRollingZIndex, zIndexBase, zIndexRange]
  )

  /* useId rather than Math.random(): the server and client renders have to agree
     on this attribute or Next.js reports a hydration mismatch. */
  const generatedId = useId()
  const id = pathId || `marquee-path-${generatedId}`

  // Scroll tracking
  const { scrollY } = useScroll({
    container: (scrollContainer as RefObject<HTMLDivElement | null>) || container,
  })

  const scrollVelocity = useVelocity(scrollY)
  const smoothVelocity = useSpring(scrollVelocity, scrollSpringConfig)

  // Hover and drag state tracking
  const isHovered = useRef(false)
  const isDragging = useRef(false)
  const dragVelocity = useRef(0)

  // Direction factor for changing direction based on scroll or drag
  const directionFactor = useRef(direction === "normal" ? 1 : -1)

  // Motion values for animation
  const hoverFactorValue = useMotionValue(1)
  const defaultVelocity = useMotionValue(1)
  const smoothHoverFactor = useSpring(hoverFactorValue, slowDownSpringConfig)

  // Transform scroll velocity into a factor that affects marquee speed
  const velocityFactor = useTransform(
    useScrollVelocity ? smoothVelocity : defaultVelocity,
    [0, 1000],
    [0, 5],
    { clamp: false }
  )

  const isActive = useMarqueeActive(
    container,
    respectReducedMotion,
    pauseWhenOffscreen
  )

  // Animation frame handler
  useAnimationFrame((_, delta) => {
    /* Parked: reduced motion, offscreen, or a hidden tab. Dragging still works,
       so a reduced-motion visitor keeps a way to move through the items under
       their own control — the feedback stays, only the autoplay stops. */
    if (!isActive && !isDragging.current) return

    if (isDragging.current && draggable) {
      baseOffset.set(baseOffset.get() + dragVelocity.current)

      // Add decay to dragVelocity
      dragVelocity.current *= 0.9

      // Stop completely if velocity is very small
      if (Math.abs(dragVelocity.current) < 0.01) {
        dragVelocity.current = 0
      }

      return
    }

    // Update hover factor
    if (isHovered.current) {
      hoverFactorValue.set(slowdownOnHover ? slowDownFactor : 1)
    } else {
      hoverFactorValue.set(1)
    }

    // Calculate regular movement
    let moveBy =
      directionFactor.current *
      baseVelocity *
      (delta / 1000) *
      smoothHoverFactor.get()

    // Adjust movement based on scroll velocity if scrollAwareDirection is enabled
    if (scrollAwareDirection && !isDragging.current) {
      if (velocityFactor.get() < 0) {
        directionFactor.current = -1
      } else if (velocityFactor.get() > 0) {
        directionFactor.current = 1
      }
    }

    moveBy += directionFactor.current * moveBy * velocityFactor.get()

    if (draggable) {
      moveBy += dragVelocity.current

      // Update direction based on drag direction if dragAwareDirection is true
      if (dragAwareDirection && Math.abs(dragVelocity.current) > 0.1) {
        directionFactor.current = Math.sign(dragVelocity.current)
      }

      // Gradually decay drag velocity back to zero
      if (!isDragging.current && Math.abs(dragVelocity.current) > 0.01) {
        dragVelocity.current *= dragVelocityDecay
      } else if (!isDragging.current) {
        dragVelocity.current = 0
      }
    }

    baseOffset.set(baseOffset.get() + moveBy)
  })

  // Pointer event handlers for dragging
  const lastPointerPosition = useRef({ x: 0, y: 0 })

  const handlePointerDown = (e: React.PointerEvent) => {
    if (!draggable) return
    ;(e.currentTarget as HTMLElement).setPointerCapture(e.pointerId)

    if (grabCursor) {
      ;(e.currentTarget as HTMLElement).style.cursor = "grabbing"
    }

    isDragging.current = true
    lastPointerPosition.current = { x: e.clientX, y: e.clientY }

    // Pause automatic animation by setting velocity to 0
    dragVelocity.current = 0
  }

  const handlePointerMove = (e: React.PointerEvent) => {
    if (!draggable || !isDragging.current) return

    const currentPosition = { x: e.clientX, y: e.clientY }

    // Calculate movement delta - simplified for path movement
    const deltaX = currentPosition.x - lastPointerPosition.current.x
    const deltaY = currentPosition.y - lastPointerPosition.current.y

    // For path following, we use a simple magnitude of movement
    const delta = Math.sqrt(deltaX * deltaX + deltaY * deltaY)
    const projectedDelta = deltaX > 0 ? delta : -delta

    // Update drag velocity based on the projected movement
    dragVelocity.current = projectedDelta * dragSensitivity

    // Update last position
    lastPointerPosition.current = currentPosition
  }

  const handlePointerUp = (e: React.PointerEvent) => {
    if (!draggable) return
    ;(e.currentTarget as HTMLElement).releasePointerCapture(e.pointerId)
    isDragging.current = false

    if (grabCursor) {
      ;(e.currentTarget as HTMLElement).style.cursor = "grab"
    }
  }

  return (
    <div
      ref={container}
      onPointerDown={handlePointerDown}
      onPointerMove={handlePointerMove}
      onPointerUp={handlePointerUp}
      onPointerCancel={handlePointerUp}
      className={cn("relative", className)}
    >
      <div
        ref={marqueeContainerRef}
        className="relative"
        style={{ contain: "layout style" }}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          width={width}
          height={height}
          viewBox={viewBox}
          preserveAspectRatio={preserveAspectRatio}
          className="w-full h-full"
        >
          <path
            id={id}
            d={path}
            stroke={showPath ? "currentColor" : "none"}
            fill="none"
            ref={pathRef}
          />
        </svg>

        {items.map(({ child, repeatIndex, itemIndex, key }) => (
          <MarqueeItem
            key={key}
            child={child}
            itemIndex={itemIndex}
            itemCount={items.length}
            repeatIndex={repeatIndex}
            path={path}
            baseOffset={baseOffset}
            easing={easing}
            enableRollingZIndex={enableRollingZIndex}
            calculateZIndex={calculateZIndex}
            cssVariableInterpolation={cssVariableInterpolation}
            draggable={draggable}
            grabCursor={grabCursor}
            isActive={isActive}
            followPathRotation={followPathRotation}
            onHoverChange={(hovered) => (isHovered.current = hovered)}
            itemRef={(el) => {
              if (el) itemRefs.current.set(key, el)
            }}
          />
        ))}
      </div>
    </div>
  )
}

export default MarqueeAlongSvgPath
