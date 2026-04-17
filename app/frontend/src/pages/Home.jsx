import React from 'react';
import Hero from '../components/sections/Hero';
import LogoCloud from '../components/sections/LogoCloud';
import FeaturesGrid from '../components/sections/FeaturesGrid';
import Testimonials from '../components/sections/Testimonials';
import Awards from '../components/sections/Awards';
import CtaBand from '../components/sections/CtaBand';

export default function Home() {
  return (
    <>
      <Hero />
      <LogoCloud />
      <FeaturesGrid />
      <Testimonials />
      <Awards />
      <CtaBand />
    </>
  );
}
