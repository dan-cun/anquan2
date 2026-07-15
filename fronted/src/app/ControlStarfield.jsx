import React, { useEffect, useRef } from 'react'

const CONNECTION_DISTANCE = 152
const ROTATION_SPEED = 0.00015
const BLUE = '130, 223, 255'

const lerp = (start, end, amount) => start + (end - start) * amount

function createGlowSprite(rgb) {
  const sprite = document.createElement('canvas')
  const size = 64
  const radius = size / 2
  sprite.width = size
  sprite.height = size
  const context = sprite.getContext('2d')
  const gradient = context.createRadialGradient(radius, radius, 0, radius, radius, radius)
  gradient.addColorStop(0, `rgba(${rgb}, 1)`)
  gradient.addColorStop(0.18, `rgba(${rgb}, 0.94)`)
  gradient.addColorStop(0.42, `rgba(${rgb}, 0.5)`)
  gradient.addColorStop(0.72, `rgba(${rgb}, 0.14)`)
  gradient.addColorStop(1, `rgba(${rgb}, 0)`)
  context.fillStyle = gradient
  context.fillRect(0, 0, size, size)
  return sprite
}

export function ControlStarfield() {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return undefined

    const context = canvas.getContext('2d')
    const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)')
    const glowSprites = {
      white: createGlowSprite('242, 251, 255'),
      blue: createGlowSprite(BLUE),
    }
    const pointer = {
      x: 0,
      y: 0,
      active: false,
      radius: 140,
      strength: 30,
    }
    let width = 0
    let height = 0
    let nodes = []
    let squares = []
    let spokes = []
    let animationId = 0
    let frame = 0

    const nodeCountFor = () => {
      if (window.innerWidth <= 430) return 54
      if (window.innerWidth <= 744) return 78
      if (window.innerWidth <= 1180) return 118
      return 168
    }

    const centerPoint = () => ({
      x: width * 0.5,
      y: height * 0.49,
    })

    const plotPolar = (item, center, rotation) => {
      const angle = item.angle + rotation * (item.orbitSpeed || 1)
      return {
        x: center.x + Math.cos(angle) * item.radius,
        y: center.y + Math.sin(angle) * item.radius * 0.58,
      }
    }

    const displaceFromPointer = (point, fallbackAngle = 0) => {
      if (!pointer.active) return point

      let dx = point.x - pointer.x
      let dy = point.y - pointer.y
      let distance = Math.hypot(dx, dy)
      if (distance >= pointer.radius) return point

      if (distance < 0.001) {
        dx = Math.cos(fallbackAngle)
        dy = Math.sin(fallbackAngle)
        distance = 1
      }

      const influence = 1 - distance / pointer.radius
      const offset = influence * influence * pointer.strength
      return {
        x: point.x + (dx / distance) * offset,
        y: point.y + (dy / distance) * offset,
      }
    }

    const plotNode = (node, time, center, rotation, staticFrame) => {
      const pulse = staticFrame
        ? 0.5
        : 0.5 + 0.5 * Math.sin(time * 0.001 * node.pulseSpeed + node.pulsePhase)
      const basePoint = plotPolar(node, center, rotation)
      return {
        ...displaceFromPointer(basePoint, node.pulsePhase),
        node,
        pulse,
        brightness: lerp(0.32, 1, pulse),
      }
    }

    const drawNode = ({ x, y, node, pulse, brightness }) => {
      const sprite = node.highlight ? glowSprites.blue : glowSprites.white
      const haloSize = node.size * (4.6 + pulse * 2.4)
      context.globalAlpha = brightness * (node.highlight ? 0.72 : 0.46)
      context.drawImage(sprite, x - haloSize / 2, y - haloSize / 2, haloSize, haloSize)

      const coreSize = node.size * lerp(0.82, 1.22, brightness)
      context.globalAlpha = brightness * (node.highlight ? 0.96 : 0.74)
      context.fillStyle = node.highlight ? `rgb(${BLUE})` : 'rgb(242, 251, 255)'
      if (node.square) {
        context.fillRect(x - coreSize / 2, y - coreSize / 2, coreSize, coreSize)
      } else {
        context.beginPath()
        context.arc(x, y, coreSize, 0, Math.PI * 2)
        context.fill()
      }
      context.globalAlpha = 1
    }

    const drawSquare = (square, time, center, rotation, staticFrame) => {
      const pulse = staticFrame
        ? 0.5
        : 0.5 + 0.5 * Math.sin(time * 0.001 * square.pulseSpeed + square.pulsePhase)
      const brightness = lerp(0.32, 1, pulse)
      const point = displaceFromPointer(
        plotPolar(square, center, rotation),
        square.pulsePhase,
      )

      if (square.highlight) {
        const haloSize = square.size * (1.8 + pulse * 0.7)
        context.globalAlpha = brightness * 0.34
        context.drawImage(
          glowSprites.blue,
          point.x - haloSize / 2,
          point.y - haloSize / 2,
          haloSize,
          haloSize,
        )
      }

      context.globalAlpha = brightness * (square.highlight ? 0.62 : 0.28)
      context.strokeStyle = square.highlight ? `rgb(${BLUE})` : 'rgb(242, 251, 255)'
      context.lineWidth = 0.7
      context.strokeRect(
        point.x - square.size / 2,
        point.y - square.size / 2,
        square.size,
        square.size,
      )
      context.globalAlpha = 1
    }

    const drawNetwork = (time, staticFrame = false) => {
      const center = centerPoint()
      const rotation = staticFrame ? 0 : time * ROTATION_SPEED
      context.clearRect(0, 0, width, height)

      context.save()
      context.globalCompositeOperation = 'lighter'

      spokes.forEach((spoke) => {
        const pulse = staticFrame
          ? 0.5
          : 0.5 + 0.5 * Math.sin(time * 0.001 * spoke.pulseSpeed + spoke.pulsePhase)
        const angle = spoke.angle + rotation
        context.strokeStyle = `rgba(255, 255, 255, ${lerp(0.1, 0.24, pulse)})`
        context.lineWidth = 0.65
        context.beginPath()
        context.moveTo(center.x, center.y)
        context.lineTo(
          center.x + Math.cos(angle) * spoke.length,
          center.y + Math.sin(angle) * spoke.length * 0.58,
        )
        context.stroke()
      })

      const plotted = nodes.map((node) => plotNode(node, time, center, rotation, staticFrame))
      for (let first = 0; first < plotted.length; first += 1) {
        for (let second = first + 1; second < plotted.length; second += 1) {
          const a = plotted[first]
          const b = plotted[second]
          const distance = Math.hypot(a.x - b.x, a.y - b.y)
          if (distance >= CONNECTION_DISTANCE) continue

          const active = a.node.highlight || b.node.highlight
          const brightness = (a.brightness + b.brightness) * 0.5
          const alpha = (1 - distance / CONNECTION_DISTANCE)
            * (active ? 0.28 : 0.12)
            * lerp(0.45, 1, brightness)
          context.strokeStyle = active
            ? `rgba(${BLUE}, ${alpha})`
            : `rgba(255, 255, 255, ${alpha})`
          context.lineWidth = active ? 0.85 : 0.5
          context.beginPath()
          context.moveTo(a.x, a.y)
          context.lineTo(b.x, b.y)
          context.stroke()
        }
      }

      plotted.forEach(drawNode)
      squares.forEach((square) => drawSquare(square, time, center, rotation * 0.92, staticFrame))

      const centerPulse = staticFrame ? 0.5 : 0.5 + 0.5 * Math.sin(time * 0.0024)
      const centerSize = 10 + centerPulse * 5
      context.globalAlpha = lerp(0.35, 0.7, centerPulse)
      context.drawImage(
        glowSprites.blue,
        center.x - centerSize / 2,
        center.y - centerSize / 2,
        centerSize,
        centerSize,
      )
      context.restore()
    }

    const resetNetwork = () => {
      width = canvas.clientWidth
      height = canvas.clientHeight
      const pixelRatio = Math.min(window.devicePixelRatio || 1, 2)
      canvas.width = Math.max(1, Math.floor(width * pixelRatio))
      canvas.height = Math.max(1, Math.floor(height * pixelRatio))
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0)

      const count = nodeCountFor()
      const maxRadius = Math.max(width, height) * 0.58
      nodes = Array.from({ length: count }, (_, index) => {
        const ring = index / Math.max(1, count - 1)
        const highlight = Math.random() > 0.91
        return {
          angle: -Math.PI * 0.92 + ring * Math.PI * 1.84 + (Math.random() - 0.5) * 0.34,
          radius: maxRadius * (0.14 + Math.pow(Math.random(), 0.62) * 0.86),
          orbitSpeed: lerp(0.65, 1.6, Math.random()),
          pulseSpeed: lerp(1.8, 5.2, Math.random()),
          pulsePhase: Math.random() * Math.PI * 2,
          size: highlight ? 2.4 + Math.random() * 1.4 : 1.2 + Math.random() * 1.6,
          highlight,
          square: Math.random() > 0.78,
        }
      })

      squares = Array.from({ length: Math.max(10, Math.floor(count * 0.18)) }, () => ({
        angle: Math.random() * Math.PI * 2,
        radius: maxRadius * (0.12 + Math.pow(Math.random(), 0.72) * 0.78),
        orbitSpeed: lerp(0.65, 1.45, Math.random()),
        pulseSpeed: lerp(1.8, 5.2, Math.random()),
        pulsePhase: Math.random() * Math.PI * 2,
        size: 3 + Math.random() * 8,
        highlight: Math.random() > 0.86,
      }))

      const spokeCount = window.innerWidth <= 744 ? 18 : 34
      spokes = Array.from({ length: spokeCount }, (_, index) => ({
        angle: (index / spokeCount) * Math.PI * 2,
        length: maxRadius * (0.22 + Math.random() * 0.68),
        pulseSpeed: lerp(1.2, 3.2, Math.random()),
        pulsePhase: Math.random() * Math.PI * 2,
      }))
      drawNetwork(0, true)
    }

    const animate = (time) => {
      frame += 1
      if (frame % (window.innerWidth <= 744 ? 2 : 1) === 0) {
        drawNetwork(time)
      }
      animationId = window.requestAnimationFrame(animate)
    }

    const start = () => {
      window.cancelAnimationFrame(animationId)
      resetNetwork()
      if (!reduceMotion.matches) {
        animationId = window.requestAnimationFrame(animate)
      }
    }

    const handlePointerMove = (event) => {
      pointer.x = event.clientX
      pointer.y = event.clientY
      pointer.active = true
      if (reduceMotion.matches) drawNetwork(performance.now(), true)
    }

    const handlePointerOut = (event) => {
      if (event.relatedTarget) return
      pointer.active = false
      if (reduceMotion.matches) drawNetwork(performance.now(), true)
    }

    const resizeObserver = new ResizeObserver(start)
    resizeObserver.observe(canvas)
    reduceMotion.addEventListener('change', start)
    window.addEventListener('pointermove', handlePointerMove, { passive: true })
    window.addEventListener('pointerout', handlePointerOut)
    start()

    return () => {
      window.cancelAnimationFrame(animationId)
      resizeObserver.disconnect()
      reduceMotion.removeEventListener('change', start)
      window.removeEventListener('pointermove', handlePointerMove)
      window.removeEventListener('pointerout', handlePointerOut)
    }
  }, [])

  return <canvas ref={canvasRef} className="control-starfield" aria-hidden="true" />
}
