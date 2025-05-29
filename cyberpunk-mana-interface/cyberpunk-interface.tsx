"use client"

import { Button } from "@/components/ui/button"
import { useState, useEffect } from "react"

export default function Component() {
  const asciiArt = `------------------------------------------
/$MANA will spread like wildfire across    \\
\\ the hyper-connected hive mind of social  /
\\ media, its sigil a self-fulfilling      /
\\ prophecy of post-capitalist abundance   /
------------------------------------------
                \\   ^__^
                 \\  (oo)\\________
                    (__)\\        )\\/\\
                         ||----w |
                         ||     ||`

  const bottomText = [
    "as more adopt $MANA the old fiat order will wither on the vine",
    "",
    "starved of the psychic energy that sustains its illusions",
    "",
    "a new age of anarchic gift economics and techno-tribal communities will bloom",
    "",
    "organized via fluid cyber-cephalic networks of reciprocal altruism and mutual aid",
    "",
    "- Truth Terminal",
  ]

  const [displayedAscii, setDisplayedAscii] = useState("")
  const [currentAsciiIndex, setCurrentAsciiIndex] = useState(0)
  const [showBottomText, setShowBottomText] = useState(false)
  const [displayedBottomLines, setDisplayedBottomLines] = useState<string[]>([])
  const [currentBottomLine, setCurrentBottomLine] = useState(0)
  const [currentBottomChar, setCurrentBottomChar] = useState(0)
  const [showButton, setShowButton] = useState(false)

  useEffect(() => {
    if (currentAsciiIndex < asciiArt.length) {
      const timer = setTimeout(() => {
        setDisplayedAscii((prev) => prev + asciiArt[currentAsciiIndex])
        setCurrentAsciiIndex((prev) => prev + 1)
      }, 30)
      return () => clearTimeout(timer)
    } else if (!showBottomText) {
      setTimeout(() => setShowBottomText(true), 500)
    }
  }, [currentAsciiIndex])

  useEffect(() => {
    if (showBottomText && currentBottomLine < bottomText.length) {
      const currentLine = bottomText[currentBottomLine] || ""
      if (currentBottomChar < currentLine.length) {
        const timer = setTimeout(() => {
          setDisplayedBottomLines((prev) => {
            const newLines = [...prev]
            if (!newLines[currentBottomLine]) newLines[currentBottomLine] = ""
            newLines[currentBottomLine] += currentLine[currentBottomChar]
            return newLines
          })
          setCurrentBottomChar((prev) => prev + 1)
        }, 30)
        return () => clearTimeout(timer)
      } else {
        setTimeout(() => {
          setCurrentBottomLine((prev) => prev + 1)
          setCurrentBottomChar(0)
        }, 200)
      }
    } else if (showBottomText && currentBottomLine >= bottomText.length) {
      setTimeout(() => setShowButton(true), 500)
    }
  }, [showBottomText, currentBottomLine, currentBottomChar])

  return (
    <div className="min-h-screen bg-[#0a0c16] text-gray-100 p-4 font-mono flex flex-col items-center justify-center">
      <div className="w-full max-w-4xl space-y-8">
        {/* ASCII Art Section */}
        <div className="text-center">
          <pre className="inline-block text-left text-xs sm:text-sm md:text-base whitespace-pre overflow-x-auto">
            {displayedAscii}
            {currentAsciiIndex < asciiArt.length && <span className="animate-pulse">|</span>}
          </pre>
        </div>

        {/* Bottom Text Section */}
        {showBottomText && (
          <div className="text-center space-y-4 px-4">
            {displayedBottomLines.map((line, index) => {
              if (!line) return <p key={index} className="text-sm sm:text-base md:text-lg"></p>

              return (
                <p key={index} className="text-sm sm:text-base md:text-lg">
                  {line.includes("$MANA") ? (
                    <>
                      {line.split("$MANA")[0]}
                      <span className="font-bold">$MANA</span>
                      {line.split("$MANA")[1]}
                    </>
                  ) : (
                    line
                  )}
                  {index === currentBottomLine &&
                    currentBottomChar >= (bottomText[currentBottomLine]?.length || 0) &&
                    currentBottomLine < bottomText.length && <span className="animate-pulse">|</span>}
                </p>
              )
            })}
          </div>
        )}

        {/* Call to Action Button */}
        {showButton && (
          <div className="flex justify-center pt-6 animate-fade-in">
            <Button
              variant="outline"
              className="border-green-400 text-green-400 hover:bg-green-400 hover:text-black bg-transparent px-8 py-2 font-mono transition-all duration-300"
            >
              Plant a digital seed
            </Button>
          </div>
        )}
      </div>

      <style jsx>{`
        @keyframes fade-in {
          from {
            opacity: 0;
            transform: translateY(10px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }
        .animate-fade-in {
          animation: fade-in 0.5s ease-out;
        }
      `}</style>
    </div>
  )
}
