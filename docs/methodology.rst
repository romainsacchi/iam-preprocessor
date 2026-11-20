Transport calculations
======================

Estimate travel from energy use
-------------------------------

To estimate travel, divide the energy used by the energy needed per passenger
or tonne-kilometre. The factor of 1,000 keeps the units consistent.

.. math::

   ES\;[\mathrm{billion\ km/yr}] =
   \frac{FE\;[\mathrm{EJ/yr}] \times 1000}
        {SEC\;[\mathrm{MJ/km}]}

Results are in billions of passenger-kilometres or tonne-kilometres per year.
The earlier notebook used :math:`10^6`, which overstated the result by a factor
of 1,000.

IMAGE battery-electric trucks
-----------------------------

IMAGE reports total electricity for medium and heavy trucks. The calculation
first estimates electricity used by plug-in hybrid trucks (PHEVs) from their
reported travel and energy per kilometre. It adds the results for the 10, 30,
and 60 km electric-range groups.

.. math::

   FE_{PHEV} = \sum_i ES_i \times SEC_{i,electricity} / 1000

It assigns the remaining electricity to battery-electric trucks (BEVs).

.. math::

   FE_{BEV} = \max(FE_{truck,electricity} - FE_{PHEV}, 0)

.. math::

   ES_{BEV} = FE_{BEV} \times 1000 / SEC_{BEV}

To estimate how much these trucks travel, supply their energy use per
tonne-kilometre. The world total is the sum of the regions because IMAGE gives
plug-in hybrid efficiency only by region. The tool reports substantial negative
estimates and sets them to zero. In strict mode, it stops on those cases.

Default assumptions
-------------------

The energy-use values for other vehicles in ``default_sec.yaml`` come from the
earlier notebook, which gives no source for them. Review and replace those
values before using the results in published work.
